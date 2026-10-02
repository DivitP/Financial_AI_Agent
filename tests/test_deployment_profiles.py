"""The same repository/job/API integration contract against real local and scaled services."""

import importlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.quotas import QuotaExceeded, Quotas
from settings import Settings
from scale_fixture import handler


@pytest.fixture(params=["local", "scaled"])
def profile(request, tmp_path, monkeypatch):
    schema = "test_scale_" + uuid4().hex
    postgres = os.getenv("TEST_POSTGRES_URL")
    redis = os.getenv("TEST_REDIS_URL")
    if request.param == "scaled" and not (postgres and redis):
        pytest.skip("Set TEST_POSTGRES_URL and TEST_REDIS_URL for real scaled integration")
    admin = None
    if request.param == "scaled":
        assert postgres is not None and redis is not None
        psycopg = pytest.importorskip("psycopg")
        from psycopg import sql

        admin = psycopg.connect(postgres, autocommit=True)
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        parsed = urlsplit(postgres)
        query = dict(parse_qsl(parsed.query))
        query["options"] = "-csearch_path=" + schema
        postgres = urlunsplit(parsed._replace(query=urlencode(query)))
    settings = Settings(
        _env_file=None,
        deployment_profile=request.param,  # type: ignore[call-arg]
        database_url=postgres if request.param == "scaled" else None,
        redis_url=redis if request.param == "scaled" else None,
        redis_stream=schema,
        FINANCIAL_AI_DATABASE_PATH=tmp_path / "local.db",
        FINANCIAL_AI_PERSIST_DIR=tmp_path,
        ENABLE_GROQ=False,
        ENABLE_FMP=False,
        ENABLE_LOCAL_LLM=False,
        ENABLE_KRONOS=False,
    )
    assert settings.database_path == tmp_path / "local.db"
    assert settings.persist_dir == tmp_path
    app_module = importlib.import_module("financial_ai.api.app")
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr("financial_ai.quotas.get_settings", lambda: settings)
    try:
        app = create_app()
        with TestClient(app) as client:
            yield app, client, settings
    finally:
        if admin:
            from redis import Redis

            Redis.from_url(redis).delete(schema)
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            admin.close()


def create(profile):
    app, client, _ = profile
    response = client.post("/api/v1/research-jobs", json={"ticker": "AAPL"})
    assert response.status_code == 202, response.text
    return app, client, UUID(response.json()["id"]), UUID(response.json()["run_id"])


def execute(app, job_id):
    runner = app.state.runner
    if app.state.database.postgres:
        return runner.process_one(handler)
    return runner.run(job_id, handler(app.state.repository, runner._job(job_id).run_id))


def test_profile_vertical_flow_and_duplicate_delivery(profile):
    app, client, job_id, run_id = create(profile)
    assert execute(app, job_id).status == "completed"
    snapshots = client.get(f"/api/v1/research-runs/{run_id}/snapshot").json()
    assert len(snapshots) == 5
    assert all(row["payload"]["provider"] == "offline-fixture" for row in snapshots)
    stream = client.get(f"/api/v1/research-jobs/{job_id}/events")
    assert "event: completed" in stream.text
    ids = [int(line[4:]) for line in stream.text.splitlines() if line.startswith("id: ")]
    resumed = client.get(
        f"/api/v1/research-jobs/{job_id}/events", headers={"Last-Event-ID": str(ids[-1])}
    )
    assert "id: " not in resumed.text
    if app.state.database.postgres:
        app.state.runner.redis.xadd(app.state.runner.stream, {"job_id": str(job_id)})
    execute(app, job_id)
    assert app.state.runner._job(job_id).attempt == 1
    assert client.get("/api/v1/settings/health").status_code == 200
    assert client.get("/api/v1/research-runs").status_code == 200
    assert client.get("/ready").status_code == 200
    audit = client.get(f"/api/v1/research-runs/{run_id}/audit").json()["events"]
    assert any(event["kind"] == "node" and event["duration_ms"] >= 0 for event in audit)
    assert any(event["kind"] == "job" and event["outcome"] == "completed" for event in audit)
    metrics = client.get("/api/v1/observability/metrics").json()["metrics"]
    assert any(row["kind"] == "node" and row["count"] > 0 for row in metrics)


def test_profile_transactions_and_idempotency(profile):
    app, _, job_id, run_id = create(profile)
    db = app.state.database
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute("UPDATE research_runs SET status='running' WHERE id=?", (str(run_id),))
            conn.execute("INSERT INTO job_outbox(job_id) VALUES ('missing')")
    assert app.state.repository.get_run(run_id)["status"] == "pending"
    for _ in range(2):
        app.state.repository.upsert_snapshot(run_id, "quote", "completed", {"price": 200}, None)
    assert len(app.state.repository.snapshots(run_id)) == 1
    assert app.state.runner.cancel(job_id)
    assert app.state.runner._job(job_id).status == "cancelled"


def test_profile_history_filters_and_archiving(profile):
    app, client, _, run_id = create(profile)
    path = f"/api/v1/research-runs/{run_id}/history"
    from financial_ai.storage.history import ResearchHistory

    # Direct call exposes database exceptions instead of only a safe HTTP 500.
    assert ResearchHistory(app.state.database).list()[0]["id"] == str(run_id)
    response = client.patch(path, json={"name": "100%_O'Brien thesis", "archived": True})
    assert response.status_code == 200, response.text
    assert response.json()["run"]["archived"] is True
    assert client.get("/api/v1/research-runs").json() == []
    for query in ("aapl", "THESIS", "%_", "O'Brien"):
        response = client.get(
            "/api/v1/research-runs",
            params={"q": query, "archive": "archived", "status": "pending"},
        )
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()] == [str(run_id)]
    for filters in ({"q": "missing"}, {"status": "failed"}, {"offset": 1}):
        assert (
            client.get("/api/v1/research-runs", params={"archive": "all", **filters}).json() == []
        )
    response = client.patch(path, json={"archived": False})
    assert response.status_code == 200, response.text
    assert response.json()["run"]["archived"] is False
    assert client.get("/api/v1/research-runs").json()[0]["name"] == "100%_O'Brien thesis"


def test_profile_restart_resumes_completed_steps(profile):
    app, _, job_id, run_id = create(profile)
    with app.state.database.transaction() as conn:
        conn.execute("UPDATE jobs SET status='running',attempt=1 WHERE id=?", (str(job_id),))
        conn.execute(
            """INSERT INTO job_steps(job_id,lane,status,percentage,updated_at)
            VALUES (?, 'collect', 'completed', 33, '2026-01-01T00:00:00+00:00')""",
            (str(job_id),),
        )
    if not app.state.database.postgres:
        app.state.runner.recover()
    assert execute(app, job_id).status == "completed"
    assert app.state.repository.snapshots(run_id) == []  # completed collection was not repeated
    assert app.state.runner._job(job_id).attempt == 2


def test_profile_atomic_quotas(profile):
    app, _, _, run_id = create(profile)
    quotas = Quotas(app.state.database, profile[2].model_copy(update={"run_call_budget": 2}))

    def charge(_):
        try:
            with quotas.context(run_id):
                quotas.charge("calls")
            return 1
        except QuotaExceeded:
            return 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(charge, range(8))) == 2


def test_profile_migration_roundtrip(profile):
    db = profile[0].state.database
    db.migrate_to(0)
    assert db.current_version() == 0
    db.migrate_to_latest()
    assert db.current_version() == 14
