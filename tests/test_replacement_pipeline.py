"""Replacement worker integration: API jobs through evidence, report and cited Q&A."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.llm.contracts import ChatResponse
from financial_ai.workflow.local_worker import process_one
from financial_ai.workflow.pipeline import ResearchPipeline


class FixtureCollector:
    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def collect(self, lane, run):
        self.calls.append(lane)
        if lane == self.fail:
            raise TimeoutError("private upstream URL")
        now = datetime.now(UTC) - timedelta(seconds=1)
        payload = {
            "name": "Fixture company",
            "price": 200,
            "currency": "USD",
            "timezone": "America/New_York",
        }
        if lane == "ohlcv":
            payload = {
                "candles": [
                    {"timestamp": (now - timedelta(days=30 - i)).isoformat(), "close": 100 + i}
                    for i in range(30)
                ]
            }
        return dict(
            provider="fixture",
            url=f"https://example.test/AAPL/{lane}",
            retrieved_at=now,
            published_at=now,
            payload=payload,
            text=f"AAPL {lane} source says revenue increased. This is synthetic test data.",
        )


class ExtractiveModel:
    provider = "fixture"
    model = "fixture-v1"

    async def complete(self, messages, *, token_budget):
        context = json.loads(messages[-1].content)["context"]
        source = context[0]
        return ChatResponse(
            provider=self.provider,
            model=self.model,
            content=json.dumps({"spans": [{"chunk_id": source["id"], "quote": source["text"]}]}),
        )


def test_worker_evidence_report_and_qa_without_legacy_or_network(tmp_path):
    app = create_app(tmp_path / "research.db")
    client = TestClient(app)
    created = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()
    collector = FixtureCollector()
    factory = lambda repository, run_id: ResearchPipeline(
        repository, run_id, collector, runtime=tmp_path
    )
    job = process_one(app.state.runner, factory)
    assert job.status == "completed"
    run_id = UUID(created["id"])
    report = client.get(f"/api/v1/research-runs/{run_id}/reports/latest")
    assert report.status_code == 200
    assert len(report.json()["evidence_links"]) == 6
    assert any(r["lane"] == "technical" for r in app.state.repository.snapshots(run_id))
    app.state.qa.provider = ExtractiveModel()
    answer = asyncio.run(app.state.qa.answer(run_id, "AAPL", "revenue"))
    assert answer["claims"]
    assert all(
        c["citation"]["url"].startswith("https://example.test/AAPL/") for c in answer["claims"]
    )
    # Completed delivery is idempotent; no repeated upstream calls or duplicate evidence.
    assert process_one(app.state.runner, factory) is None
    assert len(collector.calls) == 6


def test_partial_collection_retains_report_and_retry_only_recollects_failure(tmp_path):
    app = create_app(tmp_path / "research.db")
    client = TestClient(app)
    created = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()
    collector = FixtureCollector("news")
    factory = lambda repo, ident: ResearchPipeline(repo, ident, collector, runtime=tmp_path)
    assert process_one(app.state.runner, factory).status == "failed"
    report = client.get(f"/api/v1/research-runs/{created['id']}/reports/latest").json()
    assert "news" in report["sections"][0]["findings"][0]["limitations"][-1]
    collector.fail = None
    # API retry creates a fresh durable job; successful source lanes remain cached in SQL.
    assert client.post(f"/api/v1/research-runs/{created['id']}/retry").status_code == 200
    assert process_one(app.state.runner, factory).status == "completed"
    assert collector.calls.count("quote") == 1 and collector.calls.count("news") == 2


def test_etf_resolution_skips_corporate_statements(tmp_path):
    class EtfCollector(FixtureCollector):
        def collect(self, lane, run):
            result = super().collect(lane, run)
            if lane == "instrument":
                result["payload"].update(asset_type="etf", exchange="NYSE")
            return result

    app = create_app(tmp_path / "research.db")
    client = TestClient(app)
    created = client.post("/api/v1/research-runs", json={"ticker": "SPY"}).json()
    collector = EtfCollector()
    process_one(
        app.state.runner,
        lambda repo, ident: ResearchPipeline(repo, ident, collector, runtime=tmp_path),
    )
    assert "statements" not in collector.calls and "filings" not in collector.calls
    assert client.get(f"/api/v1/research-runs/{created['id']}").json()["asset_type"] == "etf"
    snapshots = app.state.repository.snapshots(UUID(created["id"]))
    assert not any(row["lane"] == "fundamentals" for row in snapshots)
    statements = next(row for row in snapshots if row["lane"] == "statements")
    assert json.loads(statements["payload_json"])["status"] == "not_applicable"


def test_worker_restart_resumes_completed_collection(tmp_path):
    from financial_ai.workflow.jobs import LocalResearchJobRunner

    app = create_app(tmp_path / "research.db")
    created = TestClient(app).post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()
    collector = FixtureCollector()
    pipeline = ResearchPipeline(
        app.state.repository, UUID(created["id"]), collector, runtime=tmp_path
    )
    pipeline.collect()
    # Simulate termination after durable collection but before the next step.
    with app.state.database.transaction() as db:
        db.execute("UPDATE jobs SET status='running', attempt=1")
    restarted = LocalResearchJobRunner(app.state.database)
    assert len(restarted.recover()) == 1
    assert (
        process_one(
            restarted,
            lambda repo, ident: ResearchPipeline(repo, ident, collector, runtime=tmp_path),
        ).status
        == "completed"
    )
    assert len(collector.calls) == 6


def test_cancellation_in_final_step_cannot_be_overwritten(tmp_path):
    app = create_app(tmp_path / "research.db")
    client = TestClient(app)
    job = client.post("/api/v1/research-jobs", json={"ticker": "AAPL"}).json()
    ident = UUID(job["id"])

    def cancel_during_report(step):
        if step == "report":
            app.state.runner.cancel(ident)

    assert app.state.runner.run(ident, cancel_during_report).status == "cancelled"
