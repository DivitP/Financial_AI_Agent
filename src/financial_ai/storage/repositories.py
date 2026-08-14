"""Transactional repositories for typed domain records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from financial_ai.domain.models import Claim, Evidence, Instrument, MetricObservation, ResearchRun
from financial_ai.storage.database import Database


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _id(value: UUID) -> str:
    return str(value)


@dataclass(frozen=True)
class ProviderRequest:
    id: UUID
    run_id: UUID
    provider: str
    request_kind: str
    requested_at: datetime
    completed_at: datetime | None = None
    status_code: int | None = None
    raw_artifact_id: str | None = None
    error_message: str | None = None


class ResearchRepository:
    """Repository with idempotent inserts inside caller-controlled transactions."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add_instrument(
        self, instrument: Instrument, connection: sqlite3.Connection | None = None
    ) -> None:
        self._execute(
            connection,
            """
            INSERT INTO instruments(id, symbol, asset_type, name, exchange, currency)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                _id(instrument.id),
                instrument.symbol,
                instrument.asset_type.value,
                instrument.name,
                instrument.exchange or "",
                instrument.currency,
            ),
        )

    def add_run(self, run: ResearchRun, connection: sqlite3.Connection | None = None) -> None:
        self._execute(
            connection,
            """
            INSERT INTO research_runs(
                id, instrument_id, status, requested_at, started_at, completed_at,
                provider_config_version, scope_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                _id(run.id),
                _id(run.instrument_id),
                run.status.value,
                _timestamp(run.requested_at),
                _timestamp(run.started_at),
                _timestamp(run.completed_at),
                run.provider_config_version,
                json.dumps(run.scope, sort_keys=True),
            ),
        )

    def update_run_status(
        self, run_id: UUID, status: str, connection: sqlite3.Connection | None = None
    ) -> None:
        self._execute(
            connection,
            "UPDATE research_runs SET status = ? WHERE id = ?",
            (status, _id(run_id)),
        )

    def get_run(self, run_id: UUID) -> sqlite3.Row | None:
        with self.database.connect() as connection:
            return connection.execute(
                """
                SELECT research_runs.*, instruments.symbol
                FROM research_runs JOIN instruments ON instruments.id = research_runs.instrument_id
                WHERE research_runs.id = ?
                """,
                (_id(run_id),),
            ).fetchone()

    def upsert_snapshot(
        self,
        run_id: UUID,
        lane: str,
        status: str,
        payload: dict[str, object] | None,
        error_message: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        now = datetime.now().astimezone().isoformat()
        self._execute(
            connection,
            """
            INSERT INTO research_snapshots(run_id, lane, status, payload_json, error_message, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, lane) DO UPDATE SET status=excluded.status, payload_json=excluded.payload_json,
                error_message=excluded.error_message, updated_at=excluded.updated_at
            """,
            (
                _id(run_id),
                lane,
                status,
                json.dumps(payload, sort_keys=True) if payload else None,
                error_message,
                now,
                now,
            ),
        )

    def snapshots(self, run_id: UUID) -> list[sqlite3.Row]:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM research_snapshots WHERE run_id = ? ORDER BY id", (_id(run_id),)
            ).fetchall()

    def add_evidence(
        self, evidence: Evidence, connection: sqlite3.Connection | None = None
    ) -> None:
        self._execute(
            connection,
            """
            INSERT INTO evidence(
                id, run_id, source_document_id, provider, kind, retrieved_at, locator,
                content_hash, excerpt, raw_artifact_id, source_tier, freshness, exact_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                _id(evidence.id),
                _id(evidence.run_id),
                _id(evidence.source_document_id) if evidence.source_document_id else None,
                evidence.provider,
                evidence.kind.value,
                _timestamp(evidence.retrieved_at),
                evidence.locator,
                evidence.content_hash,
                evidence.excerpt,
                evidence.raw_artifact_id,
                evidence.source_tier.value,
                evidence.freshness.value,
                str(evidence.exact_url) if evidence.exact_url else None,
            ),
        )

    def add_metric(
        self, metric: MetricObservation, connection: sqlite3.Connection | None = None
    ) -> None:
        self._execute(
            connection,
            """
            INSERT INTO metrics(
                id, run_id, instrument_id, metric_name, value, unit, observed_at, provider, evidence_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                _id(metric.id),
                _id(metric.run_id),
                _id(metric.instrument_id),
                metric.metric_name,
                metric.value,
                metric.unit,
                _timestamp(metric.observed_at),
                metric.provider,
                _id(metric.evidence_id),
            ),
        )

    def add_claim(self, claim: Claim, connection: sqlite3.Connection | None = None) -> None:
        self._execute(
            connection,
            """
            INSERT INTO claims(id, run_id, statement, evidence_ids_json, claim_type, is_model_inference)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                _id(claim.id),
                _id(claim.run_id),
                claim.statement,
                json.dumps([_id(evidence_id) for evidence_id in claim.evidence_ids]),
                claim.claim_type,
                int(claim.is_model_inference),
            ),
        )

    def add_provider_request(
        self, request: ProviderRequest, connection: sqlite3.Connection | None = None
    ) -> None:
        self._execute(
            connection,
            """
            INSERT INTO provider_requests(
                id, run_id, provider, request_kind, requested_at, completed_at,
                status_code, raw_artifact_id, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                _id(request.id),
                _id(request.run_id),
                request.provider,
                request.request_kind,
                _timestamp(request.requested_at),
                _timestamp(request.completed_at),
                request.status_code,
                request.raw_artifact_id,
                request.error_message,
            ),
        )

    def count(self, table: str) -> int:
        if table not in {
            "instruments",
            "research_runs",
            "evidence",
            "metrics",
            "claims",
            "provider_requests",
        }:
            raise ValueError("unsupported table")
        with self.database.connect() as connection:
            return int(
                connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            )

    def _execute(
        self, connection: sqlite3.Connection | None, sql: str, parameters: tuple[object, ...]
    ) -> None:
        if connection is not None:
            connection.execute(sql, parameters)
            return
        with self.database.transaction() as owned_connection:
            owned_connection.execute(sql, parameters)
