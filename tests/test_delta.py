from datetime import UTC, datetime
from uuid import UUID, uuid4
import socket

from fastapi.testclient import TestClient
from pydantic import AnyUrl

from financial_ai.api import create_app
from financial_ai.analysis.delta import LANES
from financial_ai.domain.models import Evidence, EvidenceKind


def setup_runs(tmp_path):
    app = create_app(tmp_path / "delta.db")
    client = TestClient(app)
    runs = [
        UUID(client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"])
        for _ in range(2)
    ]
    with app.state.database.transaction() as db:
        for day, run in enumerate(runs, 1):
            db.execute(
                "UPDATE research_runs SET status='completed',requested_at=? WHERE id=?",
                (f"2026-01-0{day}T00:00:00+00:00", str(run)),
            )
    evidence = []
    for run in runs:
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
                exact_url=AnyUrl(f"https://example.com/filings/{eid}"),
            )
        )
        evidence.append(str(eid))
    return app, client, runs, evidence


def test_every_lane_change_has_old_and_new_evidence_without_network(tmp_path, monkeypatch):
    app, client, runs, evidence = setup_runs(tmp_path)
    for lane in LANES:
        for i, run in enumerate(runs):
            app.state.repository.upsert_snapshot(
                run,
                lane,
                "completed",
                {"value": i + 1, "unit": "percent", "evidence_ids": [evidence[i]]},
            )

    def forbidden(*args, **kwargs):
        raise AssertionError("comparison cannot contact providers or schedule work")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(app.state.runner, "create", forbidden)
    result = client.get(f"/api/v1/research-runs/{runs[1]}/delta").json()
    assert result["previous_run_id"] == str(runs[0])
    assert {c["lane"] for c in result["changes"]} == set(LANES)
    for change in result["changes"]:
        assert change["old_evidence"][0]["id"] == evidence[0]
        assert change["new_evidence"][0]["id"] == evidence[1]
        assert change["old_evidence"][0]["exact_url"].endswith(evidence[0])
        assert change["new_evidence"][0]["exact_url"].endswith(evidence[1])


def test_gaps_uncited_changes_and_cross_run_citations_are_blocked(tmp_path):
    app, client, runs, evidence = setup_runs(tmp_path)
    repo = app.state.repository
    for i, run in enumerate(runs):
        repo.upsert_snapshot(
            run, "guidance", "completed", {"value": i, "evidence_ids": [evidence[0]]}
        )
        repo.upsert_snapshot(run, "sentiment", "completed", {"score": i})
        repo.upsert_snapshot(
            run,
            "technical",
            "completed",
            {"trend": "up", "evidence_ids": [evidence[i]], "retrieved_at": str(i)},
        )
    result = client.get(f"/api/v1/research-runs/{runs[1]}/delta").json()
    assert result["changes"] == []
    assert result["unchanged"] == ["technical"]
    assert any("sentiment: differing" in text for text in result["limitations"])
    assert any("guidance: differing" in text for text in result["limitations"])
    assert any("filings: missing" in text for text in result["limitations"])
    assert client.get(f"/api/v1/research-runs/{runs[0]}/delta").json()["previous_run_id"] is None
    assert (
        client.get(f"/api/v1/research-runs/{runs[1]}/delta?previous_run_id={runs[1]}").status_code
        == 409
    )
    other = client.post("/api/v1/research-runs", json={"ticker": "MSFT"}).json()["id"]
    assert (
        client.get(f"/api/v1/research-runs/{runs[1]}/delta?previous_run_id={other}").status_code
        == 409
    )
    assert client.get(f"/api/v1/research-runs/{other}/delta").status_code == 409
    assert client.get(f"/api/v1/research-runs/{uuid4()}/delta").status_code == 404


def test_frozen_report_snapshots_not_replaced_and_legacy_gaps_are_explicit(tmp_path):
    app, client, runs, evidence = setup_runs(tmp_path)
    repo = app.state.repository
    for i, run in enumerate(runs):
        repo.upsert_snapshot(
            run, "valuation", "completed", {"pe": 10 + i, "evidence_id": evidence[i]}
        )
        repo.upsert_report(
            report_id=uuid4(),
            run_id=run,
            version=1,
            as_of=datetime(2026, 1, i + 1, tzinfo=UTC),
            model_config={},
            decision_brief=[],
            sections=[],
            evidence_links={},
        )
        repo.upsert_snapshot(run, "valuation", "completed", {"pe": 999, "evidence_id": evidence[i]})
    path = f"/api/v1/research-runs/{runs[1]}/delta"
    result = client.get(path).json()
    assert result["changes"][0]["old"]["pe"] == 10
    assert result["changes"][0]["new"]["pe"] == 11
    assert result["basis"][str(runs[0])]["version"] == 1
    with app.state.database.transaction() as db:
        db.execute("DELETE FROM report_history")
    result = client.get(path).json()
    assert result["changes"] == []
    assert any("current data was not substituted" in text for text in result["limitations"])
