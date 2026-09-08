import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.domain.models import Evidence, EvidenceKind
from financial_ai.llm.contracts import ChatResponse
from financial_ai.retrieval.index import SourceText, chunks


def setup(tmp_path):
    app = create_app(tmp_path / "qa.db")
    client = TestClient(app)
    run = UUID(client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"])
    now = datetime(2026, 1, 1, tzinfo=UTC)
    evidence = Evidence(
        id=uuid4(),
        run_id=run,
        provider="sec",
        kind=EvidenceKind.FILING,
        retrieved_at=now,
        locator="filing",
        content_hash="test",
        exact_url="https://example.com/filing#risks",
    )
    app.state.repository.add_evidence(evidence)
    source = SourceText(
        ticker="AAPL",
        run_id=run,
        evidence_id=evidence.id,
        source_url=evidence.exact_url,
        kind="filing",
        period="2026",
        published_at=now,
        retrieved_at=now,
        text="# Risks\nRevenue faces pressure.",
    )
    app.state.qa.index.index(source)
    return app, client, run, chunks(source)[0]


class Model:
    def __init__(self, content):
        self.content = content

    async def complete(self, messages, token_budget):
        return ChatResponse(content=json.dumps(self.content), provider="fixture", model="fixture")


def test_answer_stream_and_persistent_history(tmp_path):
    app, client, run, chunk = setup(tmp_path)
    app.state.qa.provider = Model(
        {"spans": [{"chunk_id": chunk["id"], "quote": "Revenue faces pressure."}]}
    )
    response = client.post(f"/api/v1/research-runs/{run}/qa", json={"question": "Revenue risks?"})
    assert response.status_code == 200 and "event: claim" in response.text
    assert "https://example.com/filing#risks" in response.text
    restarted = TestClient(create_app(tmp_path / "qa.db"))
    assert len(restarted.get(f"/api/v1/research-runs/{run}/qa").json()) == 1


def test_invalid_model_citations_never_stream_or_persist(tmp_path):
    app, client, run, chunk = setup(tmp_path)
    for payload in (
        {"answer": "Invented uncited answer"},
        {"spans": [{"quote": "No citation"}]},
        {"spans": [{"chunk_id": "wrong-run", "quote": "Revenue faces pressure."}]},
        {"spans": [{"chunk_id": chunk["id"], "quote": "Revenue guaranteed to double."}]},
    ):
        app.state.qa.provider = Model(payload)
        response = client.post(f"/api/v1/research-runs/{run}/qa", json={"question": "Revenue?"})
        assert response.status_code == 422
        assert "event: claim" not in response.text
    assert client.get(f"/api/v1/research-runs/{run}/qa").json() == []


def test_empty_context_refuses_and_other_run_has_no_history(tmp_path):
    app, client, run, _ = setup(tmp_path)
    response = client.post(f"/api/v1/research-runs/{run}/qa", json={"question": "unfindabletopic"})
    assert "insufficient_evidence" in response.text
    other = client.post("/api/v1/research-runs", json={"ticker": "MSFT"}).json()["id"]
    assert client.get(f"/api/v1/research-runs/{other}/qa").json() == []
