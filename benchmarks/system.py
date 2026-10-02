"""Opt-in offline API/workflow benchmark. No developer database or live requests."""

import asyncio
import json
import logging
import math
import platform
import tempfile
import time
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.data.http import HttpRequest, HttpResponse, SharedHttpClient
from financial_ai.workflow.research import InitialResearchWorkflow


def p95(samples):
    return round(sorted(samples)[math.ceil(len(samples) * 0.95) - 1], 2)


def main():
    with tempfile.TemporaryDirectory(prefix="financial-ai-perf-") as directory:
        app = create_app(Path(directory) / "benchmark.db")
        logging.getLogger("financial_ai").setLevel(logging.WARNING)
        client = TestClient(app)
        # Benchmark request volume should not measure default interactive throttling.
        app.state.quotas.settings = app.state.quotas.settings.model_copy(
            update={"api_requests_per_minute": 10000}
        )
        run = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()
        run_id = UUID(run["id"])
        payload = {
            "provider": "fixture",
            "rows": [
                {"session": i, "open": 100, "high": 105, "low": 98, "close": 102, "volume": 100000}
                for i in range(10000)
            ],
        }
        app.state.repository.upsert_snapshot(run_id, "ohlcv", "completed", payload)
        path = f"/api/v1/research-runs/{run_id}/snapshot"
        first = client.get(path)
        assert first.status_code == 200
        snapshot_ms, conditional_ms = [], []
        for _ in range(20):
            start = time.perf_counter()
            response = client.get(path)
            snapshot_ms.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 200
            start = time.perf_counter()
            response = client.get(path, headers={"If-None-Match": first.headers["etag"]})
            conditional_ms.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 304
        provider_calls = []

        def transport(request, *_):
            provider_calls.append(request.url)
            return HttpResponse(200, {}, b'{"provider":"fixture","value":100}')

        http = SharedHttpClient(transport)

        async def lane(name):
            response = await asyncio.to_thread(
                http.fetch, HttpRequest("fixture", f"https://example.test/{name}")
            )
            return json.loads(response.body)

        lanes = {
            name: (lambda name=name: lane(name))
            for name in ("instrument", "quote", "ohlcv", "filings", "statements")
        }
        durations = []
        # One cold run followed by 20 fresh runs reusing only the provider cache.
        for i in range(21):
            created = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()
            workflow = InitialResearchWorkflow(app.state.repository, lanes)
            start = time.perf_counter()
            snapshots = asyncio.run(workflow.run(UUID(created["id"])))
            assert all(snapshot.status == "completed" for snapshot in snapshots)
            if i:
                durations.append((time.perf_counter() - start) * 1000)
            # These benchmark runs execute the workflow directly, not the queued runner.
            with app.state.database.transaction() as db:
                db.execute("UPDATE jobs SET status='completed' WHERE run_id=?", (created["id"],))
        assert len(provider_calls) == 5
        results = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "samples": 20,
            "snapshot_rows": 10000,
            "decoded_bytes": len(first.content),
            "compressed_bytes": int(first.headers["content-length"]),
            "cached_snapshot_p95_ms": p95(snapshot_ms),
            "conditional_snapshot_p95_ms": p95(conditional_ms),
            "warm_fixture_workflow_p95_ms": p95(durations),
            "provider_calls_cold_plus_20_warm": len(provider_calls),
            "provider_cache": http.health_summary(),
            "snapshot_cache": app.state.snapshot_reader.profile(),
        }
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
