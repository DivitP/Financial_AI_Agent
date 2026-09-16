"""Append-only local model evaluation and inference audit records."""

import json
from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4

from financial_ai.storage.database import Database


class ModelRunRepository:
    def __init__(self, database: Database):
        self.database = database

    def append(self, scope_key: str, kind: str, status: str, payload: dict) -> str:
        run_id = str(uuid4())
        with self.database.transaction() as db:
            db.execute(
                "INSERT INTO model_runs(id, scope_key, kind, status, created_at, payload_json) VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    scope_key,
                    kind,
                    status,
                    datetime.now(UTC).isoformat(),
                    json.dumps(payload, sort_keys=True, allow_nan=False),
                ),
            )
        return run_id

    def history(self, scope_key: str, kind: str) -> list[dict]:
        with closing(self.database.connect()) as db:
            return [
                dict(row) | {"payload": json.loads(row["payload_json"])}
                for row in db.execute(
                    "SELECT * FROM model_runs WHERE scope_key=? AND kind=? ORDER BY sequence DESC",
                    (scope_key, kind),
                )
            ]
