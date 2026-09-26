from datetime import UTC, datetime
from uuid import UUID, uuid4
import socket

from fastapi.testclient import TestClient
from pydantic import AnyUrl

from financial_ai.api import create_app
from financial_ai.analysis.calendar import event_date
from financial_ai.domain.models import Evidence, EvidenceKind
import pytest


def calendar_fixture(tmp_path):
    app = create_app(tmp_path / "calendar.db")
    client = TestClient(app)
    lists = [
        client.post("/api/v1/watchlists", json={"name": name}).json()["id"]
        for name in ("Stocks", "Growth")
    ]
    for list_id in lists:
        client.put(f"/api/v1/watchlists/{list_id}/items", json={"ticker": "AAPL"})
    run = UUID(client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"])
    app.state.repository.update_run_status(run, "completed")
    eid = uuid4()
    app.state.repository.add_evidence(
        Evidence(
            id=eid,
            run_id=run,
            provider="fixture",
            kind=EvidenceKind.FILING,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            locator=str(eid),
            content_hash="fixture",
            exact_url=AnyUrl("https://example.com/events/original"),
        )
    )
    return app, client, lists, run, eid


def test_all_event_types_sources_timezone_confidence_and_no_network(tmp_path, monkeypatch):
    app, client, lists, run, eid = calendar_fixture(tmp_path)
    event = {
        "title": "Saved event",
        "scheduled_at": "2026-11-02T16:30:00-05:00",
        "evidence_ids": [str(eid)],
        "date_confidence": "estimated",
        "release_session": "after_market",
    }
    payloads = {
        "earnings": {"upcoming": event},
        "guidance": {"events": [event]},
        "dividends": {"events": [event]},
        "macro": {"releases": [event]},
        "decision": {"catalysts": [event | {"due_at": event["scheduled_at"]}]},
    }
    for lane, payload in payloads.items():
        app.state.repository.upsert_snapshot(run, lane, "completed", payload)

    def forbidden(*args, **kwargs):
        raise AssertionError("Calendar cannot call providers or create jobs")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(app.state.runner, "create", forbidden)
    path = "/api/v1/calendar?start=2026-11-01&end=2026-11-30"
    result = client.get(path).json()
    assert len(result["events"]) == 5  # Membership in two watchlists is deduplicated.
    assert {e["kind"] for e in result["events"]} == {
        "earnings",
        "guidance",
        "dividend",
        "economic_release",
        "catalyst",
    }
    for item in result["events"]:
        assert item["timezone"] == "UTC-05:00"
        assert item["date_confidence"] == "estimated"
        assert item["sources"][0]["evidence"][0]["id"] == str(eid)
        assert item["sources"][0]["evidence"][0]["exact_url"].endswith("/events/original")
    assert client.get(path + "&watchlist_id=" + lists[0]).json()["events"] == result["events"]
    assert client.get("/api/v1/calendar?start=2027-01-01&end=2027-01-31").json()["events"] == []


def test_missing_dates_evidence_confidence_and_filters(tmp_path):
    app, client, lists, run, eid = calendar_fixture(tmp_path)
    valid = {"due_at": "2026-11-02", "evidence_ids": [str(eid)]}
    app.state.repository.upsert_snapshot(
        run,
        "decision",
        "completed",
        {
            "catalysts": [
                valid,
                {"due_at": "2026-11-03T16:00:00", "evidence_ids": [str(eid)]},
                {"due_at": "2026-11-04", "evidence_ids": [str(uuid4())]},
                {"evidence_ids": [str(eid)]},
            ]
        },
    )
    result = client.get("/api/v1/calendar?start=2026-11-01&end=2026-11-30").json()
    assert len(result["events"]) == 1
    assert result["events"][0]["timezone"] == "unknown (date only)"
    assert result["events"][0]["date_confidence"] == "unknown"
    assert any("ambiguous" in text for text in result["limitations"])
    assert any("evidence" in text for text in result["limitations"])
    empty = client.post("/api/v1/watchlists", json={"name": "Empty"}).json()["id"]
    assert client.get(f"/api/v1/calendar?watchlist_id={empty}").json()["events"] == []
    assert client.get(f"/api/v1/calendar?watchlist_id={uuid4()}").status_code == 404
    for query in (
        "start=bad",
        "start=2026-12-01&end=2026-01-01",
        "start=2026-01-01&end=2028-01-01",
    ):
        assert client.get("/api/v1/calendar?" + query).status_code == 422
    assert event_date("2026-11-01T01:30:00-04:00")[2] != event_date("2026-11-01T01:30:00-05:00")[2]
    with pytest.raises(ValueError):
        event_date("2026-11-01T01:30:00")
