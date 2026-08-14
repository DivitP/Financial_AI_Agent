from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from financial_ai.domain import Evidence, Instrument, ResearchRun
from financial_ai.domain.models import AssetType, EvidenceKind
from financial_ai.storage import Database, FileSystemArtifactStore, ResearchRepository


NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _records():
    instrument = Instrument(id=uuid4(), symbol="AAPL", asset_type=AssetType.EQUITY, currency="USD")
    run = ResearchRun(
        id=uuid4(),
        instrument_id=instrument.id,
        requested_at=NOW,
        provider_config_version="test",
    )
    evidence = Evidence(
        id=uuid4(),
        run_id=run.id,
        provider="sec",
        kind=EvidenceKind.FILING,
        retrieved_at=NOW,
        locator="filing-1",
        content_hash="content-hash",
    )
    return instrument, run, evidence


def test_migrations_upgrade_and_downgrade_empty_database(tmp_path) -> None:
    database = Database(tmp_path / "research.db")
    database.migrate_to_latest()
    assert database.current_version() == 4

    database.migrate_to(0)
    assert database.current_version() == 0
    with database.connect() as connection:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name = 'evidence'").fetchone()
            is None
        )


def test_migrations_downgrade_populated_database(tmp_path) -> None:
    database = Database(tmp_path / "research.db")
    database.migrate_to_latest()
    repository = ResearchRepository(database)
    instrument, run, evidence = _records()
    with database.transaction() as connection:
        repository.add_instrument(instrument, connection)
        repository.add_run(run, connection)
        repository.add_evidence(evidence, connection)

    database.migrate_to(0)
    assert database.current_version() == 0

    database.migrate_to_latest()
    assert ResearchRepository(database).count("evidence") == 0


def test_repository_writes_are_idempotent_and_rollback_on_failure(tmp_path) -> None:
    database = Database(tmp_path / "research.db")
    database.migrate_to_latest()
    repository = ResearchRepository(database)
    instrument, run, evidence = _records()

    with database.transaction() as connection:
        repository.add_instrument(instrument, connection)
        repository.add_run(run, connection)
        repository.add_evidence(evidence, connection)
        repository.add_evidence(evidence, connection)
    assert repository.count("evidence") == 1

    with pytest.raises(RuntimeError):
        with database.transaction() as connection:
            repository.add_instrument(
                Instrument(id=uuid4(), symbol="MSFT", asset_type=AssetType.EQUITY, currency="USD"),
                connection,
            )
            raise RuntimeError("force rollback")
    assert repository.count("instruments") == 1


def test_artifact_store_is_content_addressed_and_idempotent(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path / "artifacts")
    first = store.put_text('{"status":"ok"}', category="raw_response", suffix=".json")
    second = store.put_text('{"status":"ok"}', category="raw_response", suffix=".json")

    assert first == second
    assert store.exists(first, suffix=".json")
    assert store.read_bytes(first, suffix=".json") == b'{"status":"ok"}'
