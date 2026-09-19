from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.storage import ResearchRepository
from financial_ai.storage.history import ResearchHistory


def test_history_filters_names_archives_and_repeat_tickers(tmp_path):
    client = TestClient(create_app(tmp_path / "history.db"))
    first = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"]
    second = client.post("/api/v1/research-runs", json={"ticker": "AAPL"})
    assert second.status_code == 202 and second.json()["id"] != first
    path = f"/api/v1/research-runs/{first}/history"
    assert (
        client.patch(path, json={"name": " Original thesis ", "archived": True}).status_code == 200
    )
    assert len(client.get("/api/v1/research-runs").json()) == 1
    rows = client.get("/api/v1/research-runs?q=thesis&archive=archived&status=pending").json()
    assert len(rows) == 1 and rows[0]["name"] == "Original thesis"
    assert client.get("/api/v1/research-runs?archive=all&limit=1&offset=1").json()[0]["id"] in {
        first,
        second.json()["id"],
    }
    assert client.get("/api/v1/research-runs?status=completed").json() == []
    assert client.patch(path, json={"archived": False}).json()["run"]["name"] == "Original thesis"
    assert client.patch(path, json={"name": None}).json()["run"]["name"] is None
    assert "No saved report" in client.get(path).json()["notice"]
    for query in ("limit=0", "offset=-1", "archive=bad", "status=unknown"):
        assert client.get("/api/v1/research-runs?" + query).status_code == 422
    assert client.patch(path, json={"name": "a" * 81}).status_code == 422
    assert client.patch(path, json={"status": "completed"}).status_code == 422
    assert client.get(f"/api/v1/research-runs/{uuid4()}/history").status_code == 404


def test_reopening_original_version_never_substitutes_current_data(tmp_path):
    app = create_app(tmp_path / "history.db")
    client = TestClient(app)
    run_id = UUID(client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"])
    repo = ResearchRepository(app.state.database)
    path = f"/api/v1/research-runs/{run_id}/history"
    original: dict = dict(
        report_id=uuid4(),
        run_id=run_id,
        version=1,
        as_of=datetime(2025, 1, 1, tzinfo=UTC),
        model_config={"llm": "disabled"},
        decision_brief=["Original saved report"],
        sections=[],
        evidence_links={},
    )
    repo.upsert_snapshot(run_id, "quote", "completed", {"price": 100, "currency": "USD"})
    repo.upsert_report(**original)
    repo.upsert_snapshot(run_id, "quote", "completed", {"price": 200, "currency": "USD"})
    repo.upsert_report(**original)  # idempotent replay must not recapture newer snapshots
    with pytest.raises(ValueError, match="immutable"):
        repo.upsert_report(**(original | {"decision_brief": ["Replacement"]}))
    repo.upsert_report(
        **(
            original
            | {
                "report_id": uuid4(),
                "version": 2,
                "as_of": datetime(2026, 1, 1, tzinfo=UTC),
                "decision_brief": ["New version"],
            }
        )
    )
    # Reopen after a process restart, using only the database.
    reopened = TestClient(create_app(tmp_path / "history.db")).get(path).json()
    assert reopened["report"]["version"] == 1
    assert reopened["report"]["as_of"].startswith("2025-01-01")
    assert reopened["report"]["decision_brief"] == ["Original saved report"]
    assert reopened["snapshots"][0]["payload"]["price"] == 100
    assert client.get(path + "?version=2").json()["snapshots"][0]["payload"]["price"] == 200
    assert client.get(path + "?version=99").status_code == 404
    assert client.get(path + "?version=0").status_code == 422
    client.patch(path, json={"archived": True})
    assert client.get(path).json()["report"] == reopened["report"]
    # Migration round trip retains reports, explicitly declining to invent legacy snapshots.
    app.state.database.migrate_to(8)
    app.state.database.migrate_to_latest()
    legacy = ResearchHistory(app.state.database).reopen(run_id)
    assert legacy["snapshots"] == []
    assert "current snapshots are not substituted" in legacy["notice"]
    assert legacy["report"] == reopened["report"]
