from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from financial_ai.domain.models import AssetType, Instrument, ResearchRun
from financial_ai.storage import Database, ResearchRepository
from financial_ai.workflow import PersistentResearchGraph


def _repository_with_run(tmp_path) -> tuple[ResearchRepository, ResearchRun]:
    database = Database(tmp_path / "graph.db")
    database.migrate_to_latest()
    repository = ResearchRepository(database)
    instrument = Instrument(id=uuid4(), symbol="AAPL", asset_type=AssetType.EQUITY, currency="USD")
    run = ResearchRun(
        id=uuid4(),
        instrument_id=instrument.id,
        requested_at=datetime(2026, 9, 1, tzinfo=UTC),
        provider_config_version="graph-test",
    )
    with database.transaction() as connection:
        repository.add_instrument(instrument, connection)
        repository.add_run(run, connection)
    return repository, run


def test_graph_reuses_completed_checkpoints_after_restart(tmp_path) -> None:
    repository, run = _repository_with_run(tmp_path)
    calls = {"resolve": 0, "quote": 0}

    async def resolve() -> dict[str, object]:
        calls["resolve"] += 1
        return {"symbol": "AAPL"}

    async def quote_fails_once() -> dict[str, object]:
        calls["quote"] += 1
        if calls["quote"] == 1:
            raise TimeoutError("temporary provider outage")
        return {"price": 200}

    first = PersistentResearchGraph(
        repository, {"resolve": resolve, "quote": quote_fails_once}, max_retries=0
    )
    assert asyncio.run(first.run(run.id))["errors"] == {"quote": "temporary provider outage"}

    restarted = PersistentResearchGraph(repository, {"resolve": resolve, "quote": quote_fails_once})
    state = asyncio.run(restarted.run(run.id))

    assert state["outputs"] == {"resolve": {"symbol": "AAPL"}, "quote": {"price": 200}}
    assert calls == {"resolve": 1, "quote": 2}
    assert {row["node"]: row["status"] for row in repository.graph_checkpoints(run.id)} == {
        "quote": "completed",
        "resolve": "completed",
    }


def test_graph_retries_a_node_within_its_retry_budget(tmp_path) -> None:
    repository, run = _repository_with_run(tmp_path)
    attempts = 0

    async def flaky_node() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("retry me")
        return {"ok": True}

    graph = PersistentResearchGraph(repository, {"collect": flaky_node}, max_retries=1)
    assert asyncio.run(graph.run(run.id))["outputs"] == {"collect": {"ok": True}}
    assert attempts == 2
