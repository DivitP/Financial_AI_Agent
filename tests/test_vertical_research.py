"""Offline vertical research flow from HTTP request through durable evidence snapshots."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.workflow.research import InitialResearchWorkflow


def test_fixture_research_run_completes_across_api_worker_storage_and_sse(tmp_path) -> None:
    """A clean database produces the same useful snapshot without provider access."""
    app = create_app(tmp_path / "vertical.db")
    client = TestClient(app)
    created = client.post("/api/v1/research-runs", json={"ticker": "AAPL"})
    assert created.status_code == 202
    run_id = created.json()["id"]
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/providers/quote_success.json").read_text()
    )

    async def lane(payload: dict[str, object]) -> dict[str, object]:
        await asyncio.sleep(0)
        return payload

    workflow = InitialResearchWorkflow(
        app.state.repository,
        {
            "instrument": lambda: lane(
                {"name": "Apple Inc.", "exchange": "NASDAQ", "provider": "fixture-sec"}
            ),
            "quote": lambda: lane(
                {
                    **fixture["data"],
                    "retrieved_at": fixture["as_of"],
                    "provider": fixture["provider"],
                }
            ),
            "ohlcv": lambda: lane({"provider": "fixture-market", "adjustment_policy": "split"}),
            "filings": lambda: lane(
                {"url": "https://example.test/filings/AAPL", "provider": "fixture-sec"}
            ),
            "statements": lambda: lane(
                {"provider": "fixture-sec", "period": "2026-Q2", "unit": "USD"}
            ),
        },
    )
    asyncio.run(workflow.run(UUID(run_id)))

    run = client.get(f"/api/v1/research-runs/{run_id}")
    snapshot = client.get(f"/api/v1/research-runs/{run_id}/snapshot")
    assert run.json()["status"] == "completed"
    assert {item["lane"] for item in snapshot.json()} == set(workflow.required_lanes)
    assert (
        next(item for item in snapshot.json() if item["lane"] == "quote")["payload"]["price"]
        == 200.0
    )
    assert "event: queued" in client.get(f"/api/v1/research-runs/{run_id}/events").text
