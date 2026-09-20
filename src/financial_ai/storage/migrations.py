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


def _upgrade_0002(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE job_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(id),
            lane TEXT NOT NULL,
            status TEXT NOT NULL,
            percentage INTEGER NOT NULL,
            warning TEXT,
            retry_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(job_id, lane)
        );
        CREATE TABLE job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(id),
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_job_events_job_id_id ON job_events(job_id, id);
        """
    )


def _downgrade_0002(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS job_events;
        DROP TABLE IF EXISTS job_steps;
        """
    )


def _upgrade_0003(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        ALTER TABLE evidence ADD COLUMN source_tier TEXT NOT NULL DEFAULT 'official';
        ALTER TABLE evidence ADD COLUMN freshness TEXT NOT NULL DEFAULT 'unknown';
        ALTER TABLE evidence ADD COLUMN exact_url TEXT;
        """
    )


def _downgrade_0003(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        ALTER TABLE evidence DROP COLUMN exact_url;
        ALTER TABLE evidence DROP COLUMN freshness;
        ALTER TABLE evidence DROP COLUMN source_tier;
        """
    )


def _upgrade_0004(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE research_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            lane TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, lane)
        );
        CREATE INDEX idx_research_snapshots_run_id ON research_snapshots(run_id);
        """
    )


def _downgrade_0004(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS research_snapshots")


def _upgrade_0005(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE graph_checkpoints (
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            node TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT,
            error_message TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, node)
        );
        CREATE INDEX idx_graph_checkpoints_run_id ON graph_checkpoints(run_id);
        """
    )


def _downgrade_0005(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS graph_checkpoints")


def _upgrade_0006(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE reports (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES research_runs(id),
            version INTEGER NOT NULL,
            as_of TEXT NOT NULL,
            model_config_json TEXT NOT NULL,
            decision_brief_json TEXT NOT NULL,
            sections_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, version)
        );
        CREATE TABLE report_evidence_links (
            report_id TEXT NOT NULL REFERENCES reports(id),
            evidence_id TEXT NOT NULL REFERENCES evidence(id),
            exact_url TEXT NOT NULL,
            PRIMARY KEY(report_id, evidence_id)
        );
        CREATE INDEX idx_reports_run_version ON reports(run_id, version DESC);
        """
    )


def _downgrade_0006(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS report_evidence_links;
        DROP TABLE IF EXISTS reports;
        """
    )


def _upgrade_0007(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE qa_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES research_runs(id),
        question TEXT NOT NULL, answer_json TEXT NOT NULL,
        created_at TEXT NOT NULL)""")


def _downgrade_0007(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS qa_history")


def _upgrade_0008(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE model_runs (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        scope_key TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, payload_json TEXT NOT NULL)""")
    connection.execute(
        "CREATE INDEX idx_model_runs_scope ON model_runs(scope_key, kind, sequence DESC)"
    )


def _downgrade_0008(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS model_runs")


def _upgrade_0009(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE run_history_metadata (
        run_id TEXT PRIMARY KEY REFERENCES research_runs(id), name TEXT,
        archived INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE report_history (
        report_id TEXT PRIMARY KEY REFERENCES reports(id), snapshots_json TEXT NOT NULL)""")


def _downgrade_0009(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS report_history")
    connection.execute("DROP TABLE IF EXISTS run_history_metadata")


def _upgrade_0010(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE watchlists (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE watchlist_items (
        watchlist_id TEXT NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
        ticker TEXT NOT NULL, notes TEXT NOT NULL, tags_json TEXT NOT NULL,
        PRIMARY KEY(watchlist_id, ticker))""")


def _downgrade_0010(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE watchlist_items")
    connection.execute("DROP TABLE watchlists")


MIGRATIONS = (
    Migration(1, "initial_research_schema", _upgrade_0001, _downgrade_0001),
    Migration(2, "durable_job_progress", _upgrade_0002, _downgrade_0002),
    Migration(3, "evidence_source_quality", _upgrade_0003, _downgrade_0003),
    Migration(4, "initial_research_snapshots", _upgrade_0004, _downgrade_0004),
    Migration(5, "research_graph_checkpoints", _upgrade_0005, _downgrade_0005),
    Migration(6, "evidence_backed_reports", _upgrade_0006, _downgrade_0006),
    Migration(7, "research_qa_history", _upgrade_0007, _downgrade_0007),
    Migration(8, "model_run_quality_history", _upgrade_0008, _downgrade_0008),
    Migration(9, "saved_research_history", _upgrade_0009, _downgrade_0009),
    Migration(10, "persistent_watchlists", _upgrade_0010, _downgrade_0010),
)
