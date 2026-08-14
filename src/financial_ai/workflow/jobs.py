"""Durable local jobs with persisted steps, events, retry, and cancellation."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from financial_ai.storage.database import Database


JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
StepHandler = Callable[[str], None]


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Job:
    id: UUID
    run_id: UUID
    status: JobStatus
    attempt: int


@dataclass(frozen=True)
class JobEvent:
    id: int
    job_id: UUID
    kind: str
    payload: dict[str, object]
    created_at: datetime


class LocalResearchJobRunner:
    """Executes small local jobs synchronously; workers may call the same API later."""

    lanes = ("collect", "analyze", "report")

    def __init__(self, database: Database, *, max_attempts: int = 3) -> None:
        self.database = database
        self.max_attempts = max_attempts

    def create(
        self,
        run_id: UUID,
        payload: dict[str, object] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> Job:
        job = Job(id=uuid4(), run_id=run_id, status="pending", attempt=0)
        if connection is not None:
            self._insert(connection, job, payload)
            return job
        with self.database.transaction() as connection:
            self._insert(connection, job, payload)
        return job

    def recover(self) -> list[UUID]:
        """Return interrupted/failed jobs to pending when retry budget permits."""
        recovered: list[UUID] = []
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT id, attempt FROM jobs WHERE status IN ('running', 'failed')"
            ).fetchall()
            for row in rows:
                job_id = UUID(row["id"])
                if int(row["attempt"]) >= self.max_attempts:
                    continue
                connection.execute(
                    "UPDATE jobs SET status = 'pending', updated_at = ? WHERE id = ?",
                    (_now(), str(job_id)),
                )
                self._event(connection, job_id, "recovered", {"retry_state": "pending"})
                recovered.append(job_id)
        return recovered

    def cancel(self, job_id: UUID) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (str(job_id),)
            ).fetchone()
            if row is None or row["status"] in {"completed", "failed", "cancelled"}:
                return False
            connection.execute(
                "UPDATE jobs SET status = 'cancelled', updated_at = ? WHERE id = ?",
                (_now(), str(job_id)),
            )
            self._event(connection, job_id, "cancelled", {"percentage": 0})
            return True

    def run(self, job_id: UUID, handler: StepHandler | None = None) -> Job:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT run_id, status, attempt FROM jobs WHERE id = ?", (str(job_id),)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown job: {job_id}")
            if row["status"] == "cancelled":
                return Job(job_id, UUID(row["run_id"]), "cancelled", int(row["attempt"]))
            connection.execute(
                "UPDATE jobs SET status = 'running', attempt = attempt + 1, updated_at = ? WHERE id = ?",
                (_now(), str(job_id)),
            )
            self._event(connection, job_id, "started", {"percentage": 0})

        try:
            for index, lane in enumerate(self.lanes, start=1):
                if self._is_cancelled(job_id):
                    return self._job(job_id)
                percentage = index * 100 // len(self.lanes)
                with self.database.transaction() as connection:
                    connection.execute(
                        """
                        INSERT INTO job_steps(job_id, lane, status, percentage, updated_at)
                        VALUES (?, ?, 'running', ?, ?)
                        ON CONFLICT(job_id, lane) DO UPDATE SET status='running', percentage=excluded.percentage,
                            updated_at=excluded.updated_at
                        """,
                        (str(job_id), lane, percentage - 1, _now()),
                    )
                    self._event(
                        connection, job_id, "progress", {"lane": lane, "percentage": percentage - 1}
                    )
                if handler:
                    handler(lane)
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE job_steps SET status='completed', percentage=?, updated_at=? WHERE job_id=? AND lane=?",
                        (percentage, _now(), str(job_id), lane),
                    )
                    self._event(
                        connection, job_id, "progress", {"lane": lane, "percentage": percentage}
                    )
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE jobs SET status='completed', updated_at=? WHERE id=?",
                    (_now(), str(job_id)),
                )
                self._event(connection, job_id, "completed", {"percentage": 100})
        except Exception as error:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE jobs SET status='failed', error_message=?, updated_at=? WHERE id=?",
                    ("job execution failed", _now(), str(job_id)),
                )
                self._event(
                    connection,
                    job_id,
                    "failed",
                    {"retry_state": "available", "warning": str(error)[:120]},
                )
        return self._job(job_id)

    def events_after(self, job_id: UUID, last_event_id: int = 0) -> list[JobEvent]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, kind, payload_json, created_at FROM job_events WHERE job_id=? AND id>? ORDER BY id",
                (str(job_id), last_event_id),
            ).fetchall()
        return [
            JobEvent(
                id=int(row["id"]),
                job_id=job_id,
                kind=row["kind"],
                payload=json.loads(row["payload_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def cleanup(self, *, older_than: timedelta) -> int:
        cutoff = (datetime.now(UTC) - older_than).isoformat()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM jobs WHERE status IN ('completed', 'cancelled') AND updated_at < ?",
                (cutoff,),
            )
            return cursor.rowcount

    def _is_cancelled(self, job_id: UUID) -> bool:
        return self._job(job_id).status == "cancelled"

    def _job(self, job_id: UUID) -> Job:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT run_id, status, attempt FROM jobs WHERE id=?", (str(job_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown job: {job_id}")
        return Job(job_id, UUID(row["run_id"]), row["status"], int(row["attempt"]))

    @staticmethod
    def _event(connection, job_id: UUID, kind: str, payload: dict[str, object]) -> None:
        connection.execute(
            "INSERT INTO job_events(job_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (str(job_id), kind, json.dumps(payload, sort_keys=True), _now()),
        )

    def _insert(
        self, connection: sqlite3.Connection, job: Job, payload: dict[str, object] | None
    ) -> None:
        connection.execute(
            """
            INSERT INTO jobs(id, run_id, kind, status, attempt, payload_json, created_at, updated_at)
            VALUES (?, ?, 'research', 'pending', 0, ?, ?, ?)
            """,
            (
                str(job.id),
                str(job.run_id),
                json.dumps(payload or {}, sort_keys=True),
                _now(),
                _now(),
            ),
        )
        self._event(connection, job.id, "queued", {"percentage": 0})
