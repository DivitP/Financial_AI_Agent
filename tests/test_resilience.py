"""Offline fault injection: durable outcomes, bounded failures, and recovery."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from financial_ai.api import create_app
from financial_ai.workflow.graph import PersistentResearchGraph
from financial_ai.workflow.jobs import LocalResearchJobRunner
from financial_ai.workflow.research import InitialResearchWorkflow


@pytest.fixture
def workspace(tmp_path):
    app = create_app(tmp_path / "resilience.db")
    client = TestClient(app)
    response = client.post("/api/v1/research-jobs", json={"ticker": "AAPL"})
    assert response.status_code == 202
    data = response.json()
    return app, client, UUID(data["run_id"]), UUID(data["id"])


@pytest.mark.parametrize("fault", ["timeout", "malformed", "empty", "wrong_shape", "outage"])
def test_collection_never_calls_partial_results_success(workspace, fault):
    app, _, run_id, _ = workspace

    async def healthy():
        return {"provider": "fixture", "value": 100}

    async def broken():
        if fault == "timeout":
            raise TimeoutError("secret-token")
        if fault == "malformed":
            return json.loads("not json: secret-token")
        if fault == "outage":
            raise ConnectionError("secret-token")
        return {} if fault == "empty" else []

    lanes = dict.fromkeys(InitialResearchWorkflow.required_lanes, healthy)
    lanes["quote"] = broken
    snapshots = asyncio.run(InitialResearchWorkflow(app.state.repository, lanes).run(run_id))
    assert app.state.repository.get_run(run_id)["status"] == "failed"
    assert sum(s.status == "completed" for s in snapshots) == 4
    failed = next(s for s in snapshots if s.status == "failed")
    assert failed.error and "secret-token" not in failed.error
    assert len(app.state.repository.snapshots(run_id)) == 5


def test_graph_timeout_and_llm_outage_resume_without_recollecting(workspace):
    app, _, run_id, _ = workspace
    calls: list[str] = []

    async def collect():
        calls.append("collect")
        return {"evidence": "fixture-evidence"}

    async def llm():
        from financial_ai.prompts import StructuredPromptExecutor

        class OfflineModel:
            provider = "fixture"
            model = "offline"

            async def complete(self, messages, *, token_budget):
                calls.append("llm")
                raise ConnectionError("private model endpoint")

        await StructuredPromptExecutor(OfflineModel()).execute(
            "research_brief", {"evidence": "fixture-evidence"}
        )
        return {"unreachable": True}

    async def stalled():
        await asyncio.sleep(10)
        return {"never": True}

    graph = PersistentResearchGraph(
        app.state.repository,
        {"collect": collect, "llm": llm, "stalled": stalled},
        max_retries=1,
        timeout_seconds=0.01,
    )
    state = asyncio.run(graph.run(run_id))
    assert set(state["errors"]) == {"llm", "stalled"}
    assert "timed out" in state["errors"]["stalled"]
    assert "private" not in state["errors"]["llm"]
    assert calls == ["collect", "llm", "llm"]
    assert app.state.repository.get_run(run_id)["status"] == "failed"

    async def recovered():
        return {"result": "fixture"}

    restarted = PersistentResearchGraph(
        app.state.repository, {"collect": collect, "llm": recovered, "stalled": recovered}
    )
    assert not asyncio.run(restarted.run(run_id))["errors"]
    assert calls.count("collect") == 1
    assert app.state.repository.get_run(run_id)["status"] == "completed"


def test_worker_process_exit_recovers_durable_steps(workspace):
    app, _, _, job_id = workspace
    script = """
import os, sys
from uuid import UUID
from financial_ai.storage import Database
from financial_ai.workflow.jobs import LocalResearchJobRunner
runner = LocalResearchJobRunner(Database(sys.argv[1]))
def handler(lane):
    if lane == 'analyze':
        os._exit(23)
runner.run(UUID(sys.argv[2]), handler)
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(app.state.database.path), str(job_id)],
        timeout=20,
        capture_output=True,
    )
    assert process.returncode == 23
    restarted = LocalResearchJobRunner(app.state.database)
    assert restarted._job(job_id).status == "running"
    assert job_id in restarted.recover()
    calls: list[str] = []
    assert restarted.run(job_id, calls.append).status == "completed"
    assert calls == ["analyze", "report"]
    assert restarted._job(job_id).attempt == 2


def test_database_lock_leaves_job_retryable_without_false_completion(workspace, monkeypatch):
    app, _, _, job_id = workspace
    original = app.state.database.connect

    def short_wait():
        db = original()
        db.execute("PRAGMA busy_timeout=1")
        return db

    monkeypatch.setattr(app.state.database, "connect", short_wait)
    lock = original()
    try:
        lock.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            app.state.runner.run(job_id)
    finally:
        lock.rollback()
        lock.close()
    assert app.state.runner._job(job_id).status == "pending"
    assert app.state.runner._job(job_id).attempt == 0
    assert app.state.runner.run(job_id).status == "completed"


def test_failed_job_retry_recovers_run_without_hiding_failed_collection(workspace):
    app, _, run_id, job_id = workspace

    def partial(lane):
        if lane == "collect":
            app.state.repository.update_run_status(run_id, "failed")

    runner = app.state.runner
    assert runner.run(job_id, partial).status == "failed"
    assert app.state.repository.get_run(run_id)["status"] == "failed"
    assert runner.recover() == [job_id]
    retried: list[str] = []
    assert runner.run(job_id, retried.append).status == "completed"
    assert retried == ["collect", "analyze", "report"]
    assert app.state.repository.get_run(run_id)["status"] == "completed"


def test_model_oom_and_retry_exhaustion_are_visible_over_sse(workspace):
    app, client, run_id, job_id = workspace
    runner = LocalResearchJobRunner(app.state.database, max_attempts=1)

    def oom(lane):
        raise MemoryError("secret model path")

    assert runner.run(job_id, oom).status == "failed"
    assert app.state.repository.get_run(run_id)["status"] == "failed"
    events = runner.events_after(job_id)
    failure = events[-1]
    assert failure.kind == "failed"
    assert "smaller model" in str(failure.payload["warning"])
    assert failure.payload["retry_state"] == "budget_exhausted"
    assert not runner.recover()
    cursor = events[1].id
    response = client.get(
        f"/api/v1/research-jobs/{job_id}/events", headers={"Last-Event-ID": str(cursor)}
    )
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids == [event.id for event in events if event.id > cursor]
    assert len(ids) == len(set(ids))
    assert "secret model path" not in response.text
    assert "event: completed" not in response.text
    assert "event: failed" in response.text
    assert (
        client.get(
            f"/api/v1/research-jobs/{job_id}/events", headers={"Last-Event-ID": str(ids[-1])}
        ).text
        == ""
    )
