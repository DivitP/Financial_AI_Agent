"""Saved-only research history. No provider, model, or refresh dependencies."""

import json
from contextlib import closing
from datetime import UTC, datetime

from financial_ai.storage.database import Database


class ResearchHistory:
    def __init__(self, database: Database):
        self.database = database

    def list(self, *, q="", status=None, archive="active", limit=20, offset=0):
        with closing(self.database.connect()) as db:
            rows = db.execute(
                """SELECT r.id, i.symbol AS ticker, r.status, r.requested_at,
                m.name, COALESCE(m.archived,0) AS archived,
                (SELECT COUNT(*) FROM reports p WHERE p.run_id=r.id) AS report_count
                FROM research_runs r JOIN instruments i ON i.id=r.instrument_id
                LEFT JOIN run_history_metadata m ON m.run_id=r.id
                WHERE (instr(lower(i.symbol),lower(?))>0 OR instr(lower(COALESCE(m.name,'')),lower(?))>0)
                AND (? IS NULL OR r.status=?)
                AND (?='all' OR COALESCE(m.archived,0)=?)
                ORDER BY julianday(r.requested_at) DESC, r.id DESC LIMIT ? OFFSET ?""",
                (q, q, status, status, archive, int(archive == "archived"), limit, offset),
            ).fetchall()
        return [dict(r) | {"archived": bool(r["archived"])} for r in rows]

    def update(self, run_id, fields):
        with self.database.transaction() as db:
            db.execute(
                "INSERT INTO run_history_metadata(run_id, updated_at) VALUES (?,?) ON CONFLICT(run_id) DO NOTHING",
                (str(run_id), datetime.now(UTC).isoformat()),
            )
            for field in ("name", "archived"):
                if field in fields:
                    db.execute(
                        f"UPDATE run_history_metadata SET {field}=?, updated_at=? WHERE run_id=?",
                        (fields[field], datetime.now(UTC).isoformat(), str(run_id)),
                    )

    def reopen(self, run_id, version=None):
        with closing(self.database.connect()) as db:
            run = db.execute(
                """SELECT r.id, r.status, r.requested_at, i.symbol AS ticker, m.name,
                COALESCE(m.archived,0) AS archived FROM research_runs r JOIN instruments i ON i.id=r.instrument_id
                LEFT JOIN run_history_metadata m ON m.run_id=r.id WHERE r.id=?""",
                (str(run_id),),
            ).fetchone()
            if run is None:
                raise KeyError("run")
            versions = [
                dict(r)
                for r in db.execute(
                    "SELECT version, as_of, created_at FROM reports WHERE run_id=? ORDER BY version",
                    (str(run_id),),
                )
            ]
            selected = (
                version if version is not None else versions[0]["version"] if versions else None
            )
            report = db.execute(
                "SELECT * FROM reports WHERE run_id=? AND version=?", (str(run_id), selected)
            ).fetchone()
            if version is not None and report is None:
                raise KeyError("report version")
            result: dict = {
                "run": dict(run) | {"archived": bool(run["archived"])},
                "versions": versions,
                "report": None,
                "snapshots": [],
                "notice": "Saved history only. No current data was fetched.",
            }
            if report:
                result["report"] = {
                    "id": report["id"],
                    "run_id": report["run_id"],
                    "version": report["version"],
                    "as_of": report["as_of"],
                    "model_configuration": json.loads(report["model_config_json"]),
                    "decision_brief": json.loads(report["decision_brief_json"]),
                    "sections": json.loads(report["sections_json"]),
                    "evidence_links": {
                        r["evidence_id"]: r["exact_url"]
                        for r in db.execute(
                            "SELECT * FROM report_evidence_links WHERE report_id=?", (report["id"],)
                        )
                    },
                }
                saved = db.execute(
                    "SELECT snapshots_json FROM report_history WHERE report_id=?", (report["id"],)
                ).fetchone()
                if saved:
                    result["snapshots"] = [
                        {k: v for k, v in r.items() if k != "payload_json"}
                        | {"payload": json.loads(r["payload_json"]) if r["payload_json"] else None}
                        for r in json.loads(saved["snapshots_json"])
                    ]
                else:
                    result["notice"] += (
                        " Legacy report: original snapshots were not captured; current snapshots are not substituted."
                    )
            else:
                result["notice"] += " No saved report version exists for this run."
            return result
