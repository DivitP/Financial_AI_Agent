from datetime import UTC, datetime
import socket
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.storage.watchlists import Watchlists


def test_watchlist_crud_persistence_validation_and_no_jobs(tmp_path, monkeypatch):
    app = create_app(tmp_path / "lists.db")
    client = TestClient(app)

    def forbidden(*args, **kwargs):
        raise AssertionError("watchlists must not schedule research")

    monkeypatch.setattr(app.state.runner, "create", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    base = "/api/v1/watchlists"
    one = client.post(base, json={"name": " Long term "}).json()["id"]
    two = client.post(base, json={"name": "ETFs"}).json()["id"]
    item = {"ticker": "aapl", "notes": "User thesis", "tags": [" Growth ", "growth"]}
    for _ in range(2):
        response = client.put(f"{base}/{one}/items", json=item)
        assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["tags"] == ["growth"]
    assert response.json()["items"][0]["latest_run"] is None
    client.put(f"{base}/{two}/items", json={"ticker": "AAPL", "notes": "Separate notes"})
    restarted = TestClient(create_app(tmp_path / "lists.db"))
    assert len(restarted.get(base).json()) == 2
    assert restarted.get(f"{base}/{one}").json()["items"][0]["notes"] == "User thesis"
    assert client.patch(f"{base}/{one}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    for invalid in (
        {"ticker": "bad!"},
        {"ticker": "AAPL", "tags": [""]},
        {"ticker": "AAPL", "tags": ["x"] * 21},
        {"ticker": "AAPL", "notes": "x" * 2001},
    ):
        assert client.put(f"{base}/{one}/items", json=invalid).status_code == 422
    assert client.post(base, json={"name": " "}).status_code == 422
    assert client.get(f"{base}/{uuid4()}").status_code == 404
    assert client.delete(f"{base}/{one}/items/bad!").status_code == 422
    assert client.delete(f"{base}/{one}/items/aapl").json()["items"] == []
    assert len(client.get(f"{base}/{two}").json()["items"]) == 1
    assert client.delete(f"{base}/{two}").status_code == 200
    assert client.get(f"{base}/{two}").status_code == 404
    with app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM watchlist_items").fetchone()[0] == 0
    app.state.database.migrate_to(9)
    app.state.database.migrate_to_latest()
    assert client.get(base).json() == []


def test_saved_freshness_latest_run_and_upcoming_events(tmp_path):
    app = create_app(tmp_path / "lists.db")
    client = TestClient(app)
    store = Watchlists(app.state.database)
    base = "/api/v1/watchlists"
    list_id = client.post(base, json={"name": "Research"}).json()["id"]
    client.put(f"{base}/{list_id}/items", json={"ticker": "AAPL"})
    old = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"]
    new = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"]
    with app.state.database.transaction() as db:
        db.execute(
            "UPDATE research_runs SET requested_at='2025-01-01T00:00:00+00:00' WHERE id=?", (old,)
        )
        db.execute(
            "UPDATE research_runs SET requested_at='2026-01-01T00:00:00+00:00',status='failed' WHERE id=?",
            (new,),
        )
    repo = app.state.repository
    repo.upsert_snapshot(UUID(old), "quote", "completed", {"retrieved_at": "2026-01-02T00:00:00Z"})
    repo.upsert_snapshot(UUID(new), "quote", "completed", {"retrieved_at": "2025-12-01T00:00:00Z"})
    repo.upsert_snapshot(
        UUID(new),
        "earnings",
        "completed",
        {
            "provenance": [{"retrieved_at": "2026-01-01T20:00:00Z"}],
            "upcoming": {
                "scheduled_at": "2026-02-01T16:00:00-05:00",
                "exchange_session": "after_market",
                "evidence_ids": ["saved-evidence"],
            },
        },
    )
    repo.upsert_snapshot(UUID(new), "filings", "failed", None)
    repo.upsert_snapshot(UUID(new), "statements", "completed", {"retrieved_at": "2026-01-02"})
    now = datetime(2026, 1, 2, tzinfo=UTC)
    item = store.detail(list_id, now=now)["items"][0]
    assert item["latest_run"]["id"] == new and item["latest_run"]["status"] == "failed"
    states = {f["lane"]: f["state"] for f in item["freshness"]}
    assert states == {
        "quote": "stale",
        "earnings": "recent",
        "filings": "unknown",
        "statements": "unknown",
    }
    assert item["upcoming_events"][0]["release_session"] == "after_market"
    assert item["upcoming_events"][0]["evidence_ids"] == ["saved-evidence"]
    assert (
        store.detail(list_id, now=datetime(2026, 3, 1, tzinfo=UTC))["items"][0]["upcoming_events"]
        == []
    )
    # Future retrieval timestamps cannot count as fresh.
    repo.upsert_snapshot(UUID(new), "quote", "completed", {"retrieved_at": "2099-01-01T00:00:00Z"})
    assert (
        next(
            f
            for f in store.detail(list_id, now=now)["items"][0]["freshness"]
            if f["lane"] == "quote"
        )["state"]
        == "unknown"
    )
