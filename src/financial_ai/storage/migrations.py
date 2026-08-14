"""Small, dependency-free SQLite migration registry."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


MigrationOperation = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: MigrationOperation
    downgrade: MigrationOperation


def _upgrade_0001(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE instruments (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            name TEXT,
            exchange TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL,
            UNIQUE(symbol, asset_type, exchange)
        );
        CREATE TABLE research_runs (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            provider_config_version TEXT NOT NULL,
            scope_json TEXT NOT NULL
        );
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE source_documents (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            title TEXT NOT NULL,
            published_at TEXT,
            retrieved_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            artifact_id TEXT,
            terms_classification TEXT NOT NULL,
            UNIQUE(provider, canonical_url, content_hash)
        );
        CREATE TABLE evidence (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            source_document_id TEXT REFERENCES source_documents(id),
            provider TEXT NOT NULL,
            kind TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            locator TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            excerpt TEXT,
            raw_artifact_id TEXT,
            UNIQUE(run_id, provider, locator, content_hash)
        );
        CREATE TABLE metrics (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            metric_name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            provider TEXT NOT NULL,
            evidence_id TEXT NOT NULL REFERENCES evidence(id),
            UNIQUE(run_id, metric_name, observed_at, provider, evidence_id)
        );
        CREATE TABLE findings (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            summary TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            confidence REAL
        );
        CREATE TABLE claims (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            statement TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            is_model_inference INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE forecasts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            horizon TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            model_name TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL,
            validation_reference TEXT,
            evidence_ids_json TEXT NOT NULL
        );
        CREATE TABLE data_quality_issues (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            severity TEXT NOT NULL,
            code TEXT NOT NULL,
            message TEXT NOT NULL,
            evidence_id TEXT REFERENCES evidence(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE provider_requests (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            provider TEXT NOT NULL,
            request_kind TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            completed_at TEXT,
            status_code INTEGER,
            raw_artifact_id TEXT,
            error_message TEXT
        );
        CREATE INDEX idx_evidence_run_id ON evidence(run_id);
        CREATE INDEX idx_metrics_run_id ON metrics(run_id);
        CREATE INDEX idx_claims_run_id ON claims(run_id);
        CREATE INDEX idx_forecasts_run_id ON forecasts(run_id);
        """
    )


def _downgrade_0001(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS provider_requests;
        DROP TABLE IF EXISTS data_quality_issues;
        DROP TABLE IF EXISTS forecasts;
        DROP TABLE IF EXISTS claims;
        DROP TABLE IF EXISTS findings;
        DROP TABLE IF EXISTS metrics;
        DROP TABLE IF EXISTS evidence;
        DROP TABLE IF EXISTS source_documents;
        DROP TABLE IF EXISTS jobs;
        DROP TABLE IF EXISTS research_runs;
        DROP TABLE IF EXISTS instruments;
        """
    )


MIGRATIONS = (Migration(1, "initial_research_schema", _upgrade_0001, _downgrade_0001),)
