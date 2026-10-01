"""Offline attribution, trace continuity, transactional audit and secret-safety contracts."""

import asyncio
import json
import logging
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from financial_ai.api import create_app
from financial_ai.api.logging import JsonFormatter
from financial_ai.data.http import HttpRequest, HttpResponse, SharedHttpClient
from financial_ai.observability import TelemetryStore, observe, record_event, telemetry_context
from financial_ai.quotas import Quotas, complete_chat
from financial_ai.storage import Database


@pytest.fixture
def telemetry(tmp_path):
    database = Database(tmp_path / "telemetry.db")
    database.migrate_to_latest()
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield database, provider, exporter
    provider.shutdown()


def test_slow_provider_attribution_and_nested_traces(telemetry, monkeypatch):
    database, provider, exporter = telemetry
    run_id = uuid4()
    ticks = iter([0, 0, 2, 2, 2.01, 2.01])
    monkeypatch.setattr("financial_ai.observability.time.perf_counter", lambda: next(ticks))
    with telemetry_context(database, run_id, provider=provider):
        with observe("node", "filings"):
            with observe("provider", "sec"):
                pass
            with observe("provider", "gdelt"):
                pass
    rows = TelemetryStore(database).audit(run_id)
    assert rows[0]["component"] == "sec" and rows[0]["duration_ms"] == 2000
    assert rows[1]["duration_ms"] == pytest.approx(10)
    spans = exporter.get_finished_spans()
    assert spans[0].parent.span_id == spans[2].context.span_id
    assert spans[1].context.trace_id == spans[2].context.trace_id
    metrics = TelemetryStore(database).metrics()
    assert next(row for row in metrics if row["component"] == "sec")["max_ms"] == 2000


def test_cache_retries_and_model_metrics_without_network(telemetry):
    database, provider, _ = telemetry
    responses = [HttpResponse(429, {"Retry-After": "0"}, b""), HttpResponse(200, {}, b"ok")]
    client = SharedHttpClient(lambda *_: responses.pop(0), sleep=lambda _: None)
    request = HttpRequest(provider="sec", url="https://example.test/?key=SECRET")
    run_id = uuid4()

    class Model:
        provider = "groq"

        async def complete(self, *args, **kwargs):
            return "fixture"

    with telemetry_context(database, run_id, provider=provider), Quotas(database).context(run_id):
        assert client.fetch(request).status_code == 200
        assert client.fetch(request).status_code == 200
        assert asyncio.run(complete_chat(Model(), [], token_budget=10)) == "fixture"
    events = TelemetryStore(database).audit(run_id)
    assert [(e["outcome"], e["status_code"]) for e in events if e["kind"] == "provider"] == [
        ("error", 429),
        ("ok", 200),
    ]
    assert [e["outcome"] for e in events if e["kind"] == "cache"] == ["miss", "hit"]
    assert sum(e["kind"] == "model" for e in events) == 1
    assert "SECRET" not in json.dumps(events)


def test_secret_content_never_reaches_events_traces_or_logs(telemetry):
    database, provider, exporter = telemetry
    secret = "credential-from-prompt-or-url"
    run_id = uuid4()
    with telemetry_context(database, run_id, correlation_id=secret, provider=provider):
        with pytest.raises(RuntimeError), observe("provider", secret):
            raise RuntimeError(secret)
    rows = TelemetryStore(database).audit(run_id)
    assert rows[0]["component"] == "other" and rows[0]["outcome"] == "error"
    assert secret not in json.dumps(rows)
    span = exporter.get_finished_spans()[0]
    assert not span.events and span.status.description is None
    assert secret not in span.to_json()
    record = logging.LogRecord(secret, logging.ERROR, secret, 1, secret, (), None)
    record.safe_event = {"component": secret, "outcome": secret, "api_key": secret}
    assert secret not in JsonFormatter().format(record)


def test_job_trace_survives_restart_and_audit_is_transactional(tmp_path, telemetry):
    _, provider, exporter = telemetry
    path = tmp_path / "app.db"
    app = create_app(path)
    client = TestClient(app)
    with telemetry_context(app.state.database, provider=provider):
        created = client.post("/api/v1/research-jobs", json={"ticker": "AAPL"}).json()
    restarted = create_app(path)
    with telemetry_context(restarted.state.database, provider=provider):
        restarted.state.runner.run(UUID(created["id"]))
    spans = exporter.get_finished_spans()
    api_span = next(s for s in spans if s.name == "api.api")
    worker = next(s for s in spans if s.name == "workflow.research")
    assert worker.context.trace_id == api_span.context.trace_id
    assert worker.parent.span_id == api_span.context.span_id
    run_id = UUID(created["run_id"])
    store = TelemetryStore(restarted.state.database)
    before = store.audit(run_id)
    with pytest.raises(RuntimeError):
        with restarted.state.database.transaction() as connection:
            restarted.state.repository.update_run_status(run_id, "failed", connection)
            raise RuntimeError("rollback")
    assert store.audit(run_id) == before
    response = TestClient(restarted).get(f"/api/v1/research-runs/{run_id}/audit?limit=1")
    assert response.status_code == 200
    first = response.json()["events"][0]
    assert first["outcome"] == "queued"
    resumed = client.get(f"/api/v1/research-runs/{run_id}/audit?after={first['id']}").json()[
        "events"
    ]
    assert all(e["id"] > first["id"] for e in resumed)
    assert any(e["outcome"] == "completed" for e in resumed)
    assert client.get("/api/v1/observability/metrics").status_code == 200
    assert client.get("/api/v1/observability/metrics?minutes=0").status_code == 422
    assert client.get(f"/api/v1/research-runs/{uuid4()}/audit").status_code == 404


def test_context_isolation_and_diagnostic_failure_is_nonfatal(telemetry, monkeypatch):
    database, provider, _ = telemetry
    first, second = uuid4(), uuid4()

    async def lane(run):
        with telemetry_context(database, run, provider=provider):
            await asyncio.sleep(0)
            record_event("cache", "sec", "hit")

    async def together():
        await asyncio.gather(lane(first), lane(second))

    asyncio.run(together())
    assert len(TelemetryStore(database).audit(first)) == 1
    assert len(TelemetryStore(database).audit(second)) == 1
    monkeypatch.setattr(database, "connect", lambda: (_ for _ in ()).throw(RuntimeError("secret")))
    with telemetry_context(database, first, provider=provider), observe("node", "filings"):
        pass


def test_diagnostic_retention_preserves_audit(telemetry):
    database, provider, _ = telemetry
    run_id = uuid4()
    with telemetry_context(database, run_id, provider=provider):
        record_event("run", "research", "completed")
        record_event("provider", "sec")
    with database.transaction() as connection:
        connection.execute("UPDATE telemetry_events SET created_at=0")
    store = TelemetryStore(database)
    store.cleanup()
    assert [event["kind"] for event in store.audit(run_id)] == ["run"]
