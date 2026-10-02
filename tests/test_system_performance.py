"""Structural performance guarantees; timings live in the opt-in benchmark."""

import json
import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.data.http import HttpRequest, HttpResponse, SharedHttpClient
from financial_ai.providers.sec import SecFilingCollector


def test_benchmark_queues_cold_requests_under_provider_limit(monkeypatch, capsys):
    from benchmarks import system

    def slow_client(transport):
        def slow_transport(*args):
            # Force overlap that fast local fixtures can accidentally conceal.
            time.sleep(0.05)
            return transport(*args)

        return SharedHttpClient(slow_transport)

    monkeypatch.setattr(system, "SharedHttpClient", slow_client)
    system.main()
    result = json.loads(capsys.readouterr().out)
    assert result["provider_calls_cold_plus_20_warm"] == 5
    assert result["provider_cache"]["hits"] == 100


def test_snapshot_cache_revision_pagination_compression_and_streams(tmp_path):
    app = create_app(tmp_path / "performance.db")
    client = TestClient(app)
    created = client.post("/api/v1/research-jobs", json={"ticker": "AAPL"}).json()
    run_id = UUID(created["run_id"])
    repo = app.state.repository
    repo.upsert_snapshot(run_id, "quote", "completed", {"price": 100, "text": "fixture" * 2000})
    repo.upsert_snapshot(run_id, "filings", "completed", {"items": []})
    path = f"/api/v1/research-runs/{run_id}/snapshot"
    first = client.get(path, params={"limit": 1}, headers={"Accept-Encoding": "gzip"})
    assert first.status_code == 200 and first.headers["content-encoding"] == "gzip"
    assert first.json()[0]["payload"]["price"] == 100
    second = client.get(path, params={"limit": 1})
    assert second.json() == first.json()
    assert app.state.snapshot_reader.profile()["hits"] == 1
    cached = client.get(path, params={"limit": 1}, headers={"If-None-Match": first.headers["etag"]})
    assert cached.status_code == 304 and cached.content == b""
    assert client.get(path, params={"offset": 1, "limit": 1}).json()[0]["lane"] == "filings"
    assert client.get(path, params={"lane": "filings"}).json()[0]["lane"] == "filings"
    assert client.get(path, params={"limit": 51}).status_code == 422
    repo.upsert_snapshot(run_id, "quote", "completed", {"price": 101})
    updated = client.get(
        path, params={"limit": 1}, headers={"If-None-Match": first.headers["etag"]}
    )
    assert updated.status_code == 200 and updated.json()[0]["payload"]["price"] == 101
    assert updated.headers["etag"] != first.headers["etag"]
    repo.upsert_snapshot(run_id, "kronos", "completed", {})
    assert client.get(path).headers["cache-control"] == "no-store"
    client.post(f"/api/v1/research-jobs/{created['id']}/run")
    stream = client.get(
        f"/api/v1/research-jobs/{created['id']}/events", headers={"Accept-Encoding": "gzip"}
    )
    assert "content-encoding" not in stream.headers
    with app.state.database.connect() as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM research_snapshots WHERE run_id=? ORDER BY id LIMIT 10",
            (str(run_id),),
        ).fetchall()
    assert any("SEARCH" in row["detail"] and "INDEX" in row["detail"] for row in plan)
    assert not any("TEMP B-TREE" in row["detail"] for row in plan)


def test_provider_cache_bounds_ttl_auth_isolation_and_batch_failures():
    now = [0.0]
    calls = []

    def transport(request, *_):
        calls.append(request)
        if request.url.endswith("fail"):
            raise TimeoutError("fixture unavailable")
        return HttpResponse(200, {}, b"data")

    http = SharedHttpClient(
        transport, cache_max_entries=2, cache_max_bytes=8, monotonic=lambda: now[0]
    )
    a, b, fail = [HttpRequest("sec", "https://example.test/" + name) for name in ("a", "b", "fail")]
    results = http.fetch_many([a, a, b, fail])
    assert results[0] == results[1] and isinstance(results[-1], TimeoutError)
    assert len(calls) == 3
    http.fetch(a)
    http.fetch(HttpRequest("sec", a.url, headers={"Authorization": "fixture-only"}))
    assert len(calls) == 4  # Credential identities cannot share responses.
    assert http.health_summary()["evictions"] == 1
    assert http.health_summary()["bytes"] <= 8
    assert "fixture-only" not in json.dumps(http.health_summary())
    now[0] = 500
    http.fetch(a)
    assert len(calls) == 5
    with pytest.raises(ValueError):
        http.fetch_many([a] * 51)


def test_sec_batches_share_mapping_and_preserve_missing_companies():
    calls = []

    def transport(request, *_):
        calls.append(request.url)
        payload = (
            {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple"}}
            if request.url.endswith("company_tickers.json")
            else {"filings": {"recent": {}}}
        )
        return HttpResponse(200, {}, json.dumps(payload).encode())

    collector = SecFilingCollector(SharedHttpClient(transport))
    assert collector.collect_filings_many(["AAPL", "aapl", "UNKNOWN"]) == {
        "AAPL": [],
        "UNKNOWN": [],
    }
    assert len(calls) == 2


def test_qa_cursor_pages_use_index(tmp_path):
    app = create_app(tmp_path / "qa.db")
    client = TestClient(app)
    run_id = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"]
    with app.state.database.transaction() as db:
        for i in range(5):
            db.execute(
                "INSERT INTO qa_history(run_id,question,answer_json,created_at) VALUES (?,?,?,?)",
                (run_id, str(i), "{}", "2026-10-01"),
            )
    path = f"/api/v1/research-runs/{run_id}/qa"
    recent = client.get(path, params={"limit": 2}).json()
    older = client.get(path, params={"limit": 2, "before": recent[0]["id"]}).json()
    assert [row["question"] for row in recent] == ["3", "4"]
    assert [row["question"] for row in older] == ["1", "2"]
