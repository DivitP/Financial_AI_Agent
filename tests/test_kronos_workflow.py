import asyncio
import json
from uuid import UUID

from fastapi.testclient import TestClient

from settings import Settings
from financial_ai.api.app import create_app
from financial_ai.kronos.inference import LocalKronosProvider, InferenceConfig
from financial_ai.workflow.kronos import KronosWorkflowNode
from financial_ai.workflow.research import InitialResearchWorkflow
from test_kronos_preprocessing import bar, stamp


def setup(tmp_path, monkeypatch, *, fail=False):
    app = create_app(tmp_path / "api.db")
    settings = Settings(_env_file=None, ENABLE_KRONOS=True, ENABLE_GROQ=False, ENABLE_FMP=False)
    provider = LocalKronosProvider(
        enabled=True,
        assets=tmp_path / "assets",
        source=tmp_path / "source",
        cache=tmp_path / "cache.db",
        config=InferenceConfig(sample_count=2),
    )
    calls = []

    def execute(request):
        calls.append(request)
        if fail:
            raise TimeoutError("private provider detail")
        candles = [
            dict(session=t[:10], open=50, high=50, low=50, close=50, volume=100)
            for t in request["prepared"]["future_timestamps"]
        ]
        return {"paths": [candles, candles], "device": "cpu"}

    monkeypatch.setattr(provider, "_execute", execute)
    node = KronosWorkflowNode(app.state.repository, settings, provider=provider)
    app.state.kronos = node
    return app, TestClient(app), node, calls


def input_data():
    return {
        "kronos_input": {
            "candles": [bar(d, 50).model_dump(mode="json") for d in [3, 4, 8, 9]],
            "sessions": [
                {"day": stamp(d).date().isoformat(), "closes_at": stamp(d).isoformat()}
                for d in [3, 4, 8, 9, 10, 11]
            ],
            "actions": [],
            "as_of": stamp(9).isoformat(),
            "timezone": "America/New_York",
            "currency": "USD",
            "provider": "fixture",
            "calendar_source": "fixture-XNYS",
            "input_policy": "raw",
            "actions_complete": True,
        }
    }


def run_workflow(app, node, run_id):
    async def success():
        return {"ok": True}

    async def prices():
        return input_data()

    lanes = {name: success for name in InitialResearchWorkflow.required_lanes}
    lanes["ohlcv"] = prices
    asyncio.run(
        InitialResearchWorkflow(app.state.repository, lanes, kronos_node=node).run(UUID(run_id))
    )


def test_workflow_api_cache_and_experimental_isolation(tmp_path, monkeypatch):
    app, client, node, calls = setup(tmp_path, monkeypatch)
    run = client.post(
        "/api/v1/research-runs",
        json={"ticker": "AAPL", "include_kronos": True, "forecast_horizon": 2},
    ).json()["id"]
    run_workflow(app, node, run)
    endpoint = f"/api/v1/research-runs/{run}/forecast"
    assert client.get(endpoint).json()["forecast"] is None
    data = client.get(endpoint + "?include_experimental=true").json()
    assert data["status"] == "completed" and data["forecast"]["research_only"]
    assert len(data["forecast"]["historical_candles"]) == 4
    with app.state.database.connect() as db:
        scope_key = db.execute(
            "SELECT scope_key FROM model_runs WHERE id=?", (data["model_run_id"],)
        ).fetchone()[0]
    node.quality.repository.append(
        scope_key,
        "evaluation",
        "experimental",
        {
            "policy": node.quality.policy.model_dump(mode="json"),
            "reasons": ["insufficient_windows"],
            "limitations": ["Fixture only"],
            "comparison": {
                "models": {
                    "kronos": {
                        "mean_window_metrics": {"mae": 2, "mase": None},
                        "turnover": 1,
                        "max_fold_end_drawdown": 0.1,
                        "windows": [
                            {"as_of": "2026-01-01", "forecast": {"sessions": ["2026-01-02"]}}
                        ],
                    }
                }
            },
        },
    )
    validation = client.get(endpoint).json()["validation"]
    assert validation["models"]["kronos"]["metrics"]["mae"] == 2
    assert validation["reasons"] == ["insufficient_windows"]
    assert len(calls) == 1
    repeated = client.post(endpoint + "?include_experimental=true").json()
    assert repeated["forecast"]["cache_hit"] and len(calls) == 1
    assert repeated["cache_key"] == data["cache_key"]
    assert calls[0]["prepared"]["instrument"] == "AAPL"
    snapshot = client.get(f"/api/v1/research-runs/{run}/snapshot").json()
    assert next(s for s in snapshot if s["lane"] == "kronos")["payload"]["forecast"] is None
    assert client.get(f"/api/v1/research-runs/{run}").json()["status"] == "completed"
    # Same prices for another symbol must not reuse a cross-instrument cache.
    other = client.post(
        "/api/v1/research-runs",
        json={"ticker": "MSFT", "include_kronos": True, "forecast_horizon": 2},
    ).json()["id"]
    run_workflow(app, node, other)
    assert len(calls) == 2


def test_failure_retries_and_keeps_other_research_completed(tmp_path, monkeypatch):
    app, client, node, calls = setup(tmp_path, monkeypatch, fail=True)
    run = client.post(
        "/api/v1/research-runs",
        json={"ticker": "AAPL", "include_kronos": True, "forecast_horizon": 2},
    ).json()["id"]
    run_workflow(app, node, run)
    result = client.get(f"/api/v1/research-runs/{run}/forecast").json()
    assert result["status"] == "failed" and len(calls) == 2
    assert "private" not in json.dumps(result)
    assert client.get(f"/api/v1/research-runs/{run}").json()["status"] == "completed"
    snapshots = app.state.repository.snapshots(UUID(run))
    assert all(r["status"] == "completed" for r in snapshots if r["lane"] != "kronos")
    stream = client.get(f"/api/v1/research-runs/{run}/events").text
    assert '"retry_state": "retrying"' in stream and '"lane": "kronos"' in stream
    with app.state.database.connect() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM model_runs WHERE kind='forecast' AND status='failed'"
            ).fetchone()[0]
            == 2
        )


def test_opt_in_missing_inputs_validation_and_cancellation(tmp_path, monkeypatch):
    app, client, node, calls = setup(tmp_path, monkeypatch)
    assert (
        client.post(
            "/api/v1/research-runs", json={"ticker": "AAPL", "forecast_horizon": 0}
        ).status_code
        == 422
    )
    run = client.post("/api/v1/research-runs", json={"ticker": "AAPL"}).json()["id"]
    assert client.post(f"/api/v1/research-runs/{run}/forecast").json()["status"] == "disabled"
    run = client.post(
        "/api/v1/research-runs", json={"ticker": "MSFT", "include_kronos": True}
    ).json()["id"]
    endpoint = f"/api/v1/research-runs/{run}/forecast"
    assert client.post(endpoint).json()["status"] == "skipped"
    client.post(f"/api/v1/research-runs/{run}/cancel")
    assert client.post(endpoint).json()["status"] == "cancelled"
    assert calls == []
