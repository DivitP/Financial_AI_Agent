"""Fixed-clock, network-free integration benchmark and negative controls."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from uuid import NAMESPACE_URL, uuid5

import pytest

from financial_ai.domain.models import AssetType, Evidence, EvidenceKind, Instrument, ResearchRun
from financial_ai.llm.contracts import ChatResponse
from financial_ai.retrieval.evaluation import (
    answer_scores,
    enforce_thresholds,
    recall_at_k,
    reciprocal_rank,
)
from financial_ai.retrieval.index import ResearchIndex, SourceText, chunks
from financial_ai.retrieval.qa import AnswerRejected, ResearchQA
from financial_ai.storage import Database, ResearchRepository

FIXTURE = json.loads((Path(__file__).parent / "fixtures/rag/benchmark.json").read_text())
NOW = datetime(2026, 9, 9, tzinfo=UTC)


class FixtureModel:
    provider = "fixture"
    model = "extractive-v1"

    def __init__(self, selected, corrupt=None):
        self.selected, self.corrupt = selected, corrupt

    async def complete(self, messages, *, token_budget):
        context = json.loads(messages[-1].content)["context"]
        payload = {
            "spans": [
                {"chunk_id": row["id"], "quote": row["text"]}
                for row in context
                if row["id"] in self.selected
            ]
        }
        if self.corrupt is not None:
            payload = self.corrupt
        return ChatResponse(content=json.dumps(payload), provider=self.provider, model=self.model)


@pytest.fixture
def benchmark(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr("financial_ai.retrieval.qa.datetime", Clock)
    db = Database(tmp_path / "source.db")
    db.migrate_to_latest()
    repo = ResearchRepository(db)
    index = ResearchIndex(db, tmp_path / "index.db")
    runs, rows = {}, {}
    for scope, ticker in (("target", "AAPL"), ("other-run", "AAPL"), ("other-ticker", "MSFT")):
        instrument = Instrument(
            id=uuid5(NAMESPACE_URL, ticker),
            symbol=ticker,
            currency="USD",
            asset_type=AssetType.EQUITY,
        )
        repo.add_instrument(instrument)
        run = ResearchRun(
            id=uuid5(NAMESPACE_URL, scope),
            instrument_id=instrument.id,
            requested_at=NOW,
            provider_config_version="fixture",
        )
        repo.add_run(run)
        runs[scope] = run.id
        for doc in FIXTURE["documents"]:
            name = scope + "/" + doc["id"]
            evidence = Evidence(
                id=uuid5(NAMESPACE_URL, name),
                run_id=run.id,
                provider="fixture",
                kind=EvidenceKind.FILING,
                retrieved_at=NOW,
                locator=name,
                content_hash=name,
                exact_url="https://example.com/" + name,
            )
            repo.add_evidence(evidence)
            source = SourceText(
                ticker=ticker,
                run_id=run.id,
                evidence_id=evidence.id,
                source_url=evidence.exact_url,
                kind="filing",
                period="2026",
                published_at=NOW,
                retrieved_at=NOW,
                text=f"# {doc['section']}\n{doc['text']}",
            )
            index.index(source)
            rows[name] = chunks(source)[0]
    return index, runs, rows


@pytest.mark.parametrize("mode", ["lexical", "hybrid"])
def test_rag_quality_thresholds(benchmark, mode):
    index, runs, rows = benchmark
    if mode == "hybrid":

        class NoisyVector:
            def upsert(self, records):
                pass

            def search(self, query, filters, limit):
                # Deliberately poor and unfiltered semantic ranking; isolation must still hold.
                return [row["id"] for row in reversed(list(rows.values()))]

        index.vector = NoisyVector()
    recalls, ranks, precision, unsupported, answered, isolated = [], [], [], [], [], []
    for case in FIXTURE["queries"]:
        gold = {rows["target/" + name]["id"] for name in case["relevant"]}
        hits, _ = index.search(
            case["question"], ticker="AAPL", run_id=runs["target"], as_of=NOW, limit=FIXTURE["k"]
        )
        ranked = [row["id"] for row in hits]
        recalls.append(recall_at_k(ranked, gold, FIXTURE["k"]))
        ranks.append(reciprocal_rank(ranked, gold))
        isolated.append(
            float(all(r["ticker"] == "AAPL" and r["run_id"] == str(runs["target"]) for r in hits))
        )
        answer = asyncio.run(
            ResearchQA(index, FixtureModel(gold)).answer(runs["target"], "AAPL", case["question"])
        )
        scores = answer_scores(answer["claims"], {r["id"]: r for r in rows.values()}, gold)
        precision.append(scores["citation_precision"])
        unsupported.append(scores["unsupported_claim_rate"])
        answered.append(float(answer["status"] == "answered"))
    future_hits = index.search(
        "Revenue", ticker="AAPL", run_id=runs["target"], as_of=NOW - timedelta(days=1)
    )[0]
    corruptions = [
        {"spans": [{"quote": "missing citation"}]},
        {
            "spans": [
                {
                    "chunk_id": rows["other-ticker/revenue"]["id"],
                    "quote": rows["other-ticker/revenue"]["text"],
                }
            ]
        },
        {
            "spans": [
                {"chunk_id": rows["target/revenue"]["id"], "quote": "Revenue guaranteed to double."}
            ]
        },
        {"html": "<b>uncited</b>"},
    ]
    rejected = []
    for query, corruption in zip(FIXTURE["adversarial_queries"], corruptions, strict=True):
        try:
            asyncio.run(
                ResearchQA(index, FixtureModel(set(), corruption)).answer(
                    runs["target"], "AAPL", query
                )
            )
        except AnswerRejected:
            rejected.append(1.0)
        else:
            rejected.append(0.0)
    scores = dict(
        recall_at_k=mean(recalls),
        mrr=mean(ranks),
        citation_precision=mean(precision),
        unsupported_claim_rate=mean(unsupported),
        answer_rate=mean(answered),
        isolation=mean(isolated),
        freshness=float(not future_hits),
        adversarial_rejection=mean(rejected),
    )
    print(
        json.dumps(
            {"mode": mode, "fixture_version": FIXTURE["version"], "scores": scores}, sort_keys=True
        )
    )
    enforce_thresholds(scores, FIXTURE["thresholds"])


def test_metric_math_and_gate_negative_controls():
    assert recall_at_k(["bad", "a", "a"], {"a", "b"}, 3) == 0.5
    assert reciprocal_rank(["bad", "a"], {"a"}) == 0.5
    assert reciprocal_rank([], {"a"}) == 0
    assert answer_scores([{"text": "invented"}], {}, set())["unsupported_claim_rate"] == 1
    for name, bounds in FIXTURE["thresholds"].items():
        with pytest.raises(AssertionError, match=name):
            enforce_thresholds({name: -1 if "min" in bounds else 1}, {name: bounds})
    with pytest.raises(AssertionError):
        enforce_thresholds({}, FIXTURE["thresholds"])


def test_fresh_observation_ranks_before_stale_and_late_retrieval_is_excluded(benchmark):
    index, runs, rows = benchmark
    for name, age, delay, text in (
        ("revenue", 365, 0, "Freshnessterm old outlook."),
        ("margin", 0, 0, "Freshnessterm new outlook."),
        ("debt", 0, 1, "Freshnessterm late outlook."),
    ):
        row = rows["target/" + name]
        index.index(
            SourceText(
                ticker="AAPL",
                run_id=runs["target"],
                evidence_id=row["evidence_id"],
                source_url=row["source_url"],
                kind="filing",
                period="2026",
                published_at=NOW - timedelta(days=age),
                retrieved_at=NOW + timedelta(days=delay),
                text=text,
            )
        )
    hits, _ = index.search("Freshnessterm", ticker="AAPL", run_id=runs["target"], as_of=NOW)
    assert [r["text"] for r in hits] == ["Freshnessterm new outlook.", "Freshnessterm old outlook."]
