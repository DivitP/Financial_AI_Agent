"""SQLite connection and migration management."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from financial_ai.storage.migrations import MIGRATIONS


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        if self.path != Path(":memory:"):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate_to_latest(self) -> None:
        self.migrate_to(MIGRATIONS[-1].version)

    def migrate_to(self, target_version: int) -> None:
        valid_versions = {0, *(migration.version for migration in MIGRATIONS)}
        if target_version not in valid_versions:
            raise ValueError(f"Unknown schema version: {target_version}")
        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
            )
            current = self.current_version(connection)
            if target_version > current:
                for migration in MIGRATIONS:
                    if current < migration.version <= target_version:
                        migration.upgrade(connection)
                        connection.execute(
                            "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                            (migration.version, migration.name),
                        )
            elif target_version < current:
                for migration in reversed(MIGRATIONS):
                    if target_version < migration.version <= current:
                        migration.downgrade(connection)
                        connection.execute(
                            "DELETE FROM schema_migrations WHERE version = ?", (migration.version,)
                        )

    def current_version(self, connection: sqlite3.Connection | None = None) -> int:
        if connection is not None:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            return int(row["version"])
        with self.connect() as owned_connection:
            table = owned_connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            return self.current_version(owned_connection) if table else 0

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
