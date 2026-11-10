"""Offline deployment contracts; not a substitute for actually booting Docker."""

import os
import io
import json
from pathlib import Path
from uuid import UUID

import pytest
import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.ops import smoke, worker_health
from financial_ai.workflow.demo import handler

ROOT = Path(__file__).resolve().parents[1]


def test_compose_services_are_non_root_persistent_and_health_gated():
    config = yaml.safe_load((ROOT / "compose.yml").read_text())
    services = config["services"]
    assert set(services) == {"postgres", "redis", "api", "worker", "web"}
    for service in services.values():
        assert str(service["user"]) not in {"root", "0", "0:0"}
        assert service["healthcheck"]["test"]
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert "env_file" not in service
        assert all(port.startswith("127.0.0.1:") for port in service.get("ports", []))
    assert set(config["volumes"]) == {"postgres", "redis", "runtime", "model-cache"}
    assert services["worker"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["api"]["environment"]["ENABLE_KRONOS"] == "false"
    assert "model-cache:/app/model-cache" in services["worker"]["volumes"]
    assert ".env" in (ROOT / ".dockerignore").read_text().splitlines()
    assert " + " not in (ROOT / "Dockerfile").read_text()


def test_demo_handler_persists_explicit_nonfinancial_output(tmp_path):
    app = create_app(tmp_path / "demo.db")
    with TestClient(app) as client:
        created = client.post("/api/v1/research-jobs", json={"ticker": "AAPL"}).json()
    run_id = UUID(created["run_id"])
    job = app.state.runner.run(UUID(created["id"]), handler(app.state.repository, run_id))
    assert job.status == "completed"
    snapshots = app.state.repository.snapshots(run_id)
    lanes = {row["lane"]: json.loads(row["payload_json"]) for row in snapshots}
    assert lanes["quote"]["price"] == lanes["ohlcv"]["candles"][-1]["close"]
    assert lanes["fundamentals"]["metrics"]["gross_margin"]["display"] == "39.0%"
    assert lanes["charts"]["charts"][0]["artifact_id"].startswith("charts_")
    assert app.state.repository.latest_report(run_id) is not None


def test_worker_health_rejects_absent_and_stale_heartbeats(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(path))
    with pytest.raises(RuntimeError):
        worker_health()
    path.touch()
    worker_health()
    os.utime(path, (1, 1))
    with pytest.raises(RuntimeError):
        worker_health()


@pytest.mark.parametrize("state", ["completed", "failed", "running"])
def test_smoke_checks_completion_and_rejects_failed_or_stuck_runs(monkeypatch, state):
    def response(request, timeout):
        assert request.headers["Host"] == "localhost:8080"
        assert timeout == 5
        data: object = {"id": "demo", "status": state}
        if request.full_url.endswith("snapshot"):
            data = [
                {"lane": "quote", "payload": {"synthetic": True}},
                {"lane": "ohlcv", "payload": {"candles": [1] * 60}},
                {"lane": "charts", "payload": {"charts": ["fixture"]}},
            ]
        if request.full_url.endswith("reports/latest"):
            data = {
                "research_mode": "synthetic",
                "sections": ["fixture"],
                "evidence_links": {"id": "url"},
            }
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr("financial_ai.ops.urllib.request.urlopen", response)
    monkeypatch.setattr("financial_ai.ops.time.sleep", lambda seconds: None)
    if state == "completed":
        smoke()
    else:
        with pytest.raises((RuntimeError, TimeoutError)):
            smoke()
