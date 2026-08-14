from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from financial_ai.domain.models import AssetType, Instrument, ResearchRun
from financial_ai.storage import Database, ResearchRepository
from financial_ai.workflow.research import InitialResearchWorkflow


def test_parallel_lanes_persist_partial_results_when_one_provider_fails(tmp_path) -> None:
    database = Database(tmp_path / "research.db")
    database.migrate_to_latest()
    repository = ResearchRepository(database)
    instrument = Instrument(id=uuid4(), symbol="AAPL", asset_type=AssetType.EQUITY, currency="USD")
    run = ResearchRun(
        id=uuid4(),
        instrument_id=instrument.id,
        requested_at=datetime(2026, 8, 14, tzinfo=UTC),
        provider_config_version="test",
    )
    with database.transaction() as connection:
        repository.add_instrument(instrument, connection)
        repository.add_run(run, connection)

    async def success(lane: str) -> dict[str, object]:
        await asyncio.sleep(0)
        return {"lane": lane}

    async def unavailable() -> dict[str, object]:
        raise RuntimeError("provider unavailable")

    workflow = InitialResearchWorkflow(
        repository,
        {
            "instrument": lambda: success("instrument"),
            "quote": lambda: success("quote"),
            "ohlcv": unavailable,
            "filings": lambda: success("filings"),
            "statements": lambda: success("statements"),
        },
    )
    snapshots = asyncio.run(workflow.run(run.id))

    assert {snapshot.lane for snapshot in snapshots if snapshot.status == "completed"} == {
        "instrument",
        "quote",
        "filings",
        "statements",
    }
    assert next(snapshot for snapshot in snapshots if snapshot.lane == "ohlcv").status == "failed"
    persisted_run = repository.get_run(run.id)
    assert persisted_run is not None and persisted_run["status"] == "completed"
    assert len(repository.snapshots(run.id)) == 5
