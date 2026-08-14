from __future__ import annotations

from fastapi.testclient import TestClient

from financial_ai.api import create_app


def test_system_endpoints_work_without_provider_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    client = TestClient(create_app(tmp_path / "api.db"))

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ok"}
    assert client.get("/version").json()["api_version"] == "v1"
    assert client.get("/openapi.json").status_code == 200


def test_invalid_request_is_safe_json_with_correlation_id(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "api.db"), raise_server_exceptions=False)
    response = client.post("/api/v1/research-jobs", json={"ticker": "bad ticker!"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["correlation_id"] == response.headers["x-correlation-id"]
    assert "traceback" not in response.text.lower()


def test_job_events_resume_after_last_event_id_without_duplicates(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "api.db"))
    created = client.post("/api/v1/research-jobs", json={"ticker": "AAPL"}).json()
    job_id = created["id"]
    assert client.post(f"/api/v1/research-jobs/{job_id}/run").json()["status"] == "completed"

    first = client.get(f"/api/v1/research-jobs/{job_id}/events")
    event_ids = [
        int(line.removeprefix("id: "))
        for line in first.text.splitlines()
        if line.startswith("id: ")
    ]
    resumed = client.get(
        f"/api/v1/research-jobs/{job_id}/events", headers={"Last-Event-ID": str(event_ids[0])}
    )
    resumed_ids = [
        int(line.removeprefix("id: "))
        for line in resumed.text.splitlines()
        if line.startswith("id: ")
    ]

    assert event_ids == sorted(set(event_ids))
    assert resumed_ids
    assert min(resumed_ids) > event_ids[0]


def test_job_cancellation_and_recovery_are_persisted(tmp_path) -> None:
    app = create_app(tmp_path / "api.db")
    client = TestClient(app)
    job_id = client.post("/api/v1/research-jobs", json={"ticker": "MSFT"}).json()["id"]
    assert client.delete(f"/api/v1/research-jobs/{job_id}").json()["status"] == "cancelled"

    runner = app.state.runner
    created = client.post("/api/v1/research-jobs", json={"ticker": "NVDA"}).json()
    failed = client.post("/api/v1/research-jobs", json={"ticker": "GOOG"}).json()
    with app.state.database.transaction() as connection:
        connection.execute("UPDATE jobs SET status='running' WHERE id=?", (created["id"],))
        connection.execute("UPDATE jobs SET status='failed' WHERE id=?", (failed["id"],))
    assert {str(job_id) for job_id in runner.recover()} == {created["id"], failed["id"]}


def test_research_run_endpoints_cover_lifecycle_states_and_snapshots(tmp_path) -> None:
    app = create_app(tmp_path / "api.db")
    client = TestClient(app)
    created = client.post("/api/v1/research-runs", json={"ticker": "AAPL"})
    run_id = created.json()["id"]
    assert created.status_code == 202 and created.json()["status"] == "pending"
    assert client.get(f"/api/v1/research-runs/{run_id}").json()["status"] == "pending"
    assert client.get(f"/api/v1/research-runs/{run_id}/snapshot").json() == []
    assert client.post(f"/api/v1/research-runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/v1/research-runs/{run_id}/retry").json()["status"] == "pending"

    for status in ("running", "completed", "failed", "cancelled"):
        with app.state.database.transaction() as connection:
            connection.execute("UPDATE research_runs SET status=? WHERE id=?", (status, run_id))
        response = client.get(f"/api/v1/research-runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["status"] == status
