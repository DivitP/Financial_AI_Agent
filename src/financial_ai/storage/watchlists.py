"""Local watchlists: no imports or calls to providers, models, or job runners."""

import json
from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4

from financial_ai.storage.database import Database


def aware_date(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


class Watchlists:
    def __init__(self, database: Database):
        self.database = database

    def lists(self):
        with closing(self.database.connect()) as db:
            return [dict(r) for r in db.execute("SELECT * FROM watchlists ORDER BY created_at, id")]

    def create(self, name):
        item = {"id": str(uuid4()), "name": name, "created_at": datetime.now(UTC).isoformat()}
        with self.database.transaction() as db:
            db.execute("INSERT INTO watchlists VALUES (:id,:name,:created_at)", item)
        return item

    def change(self, list_id, *, name=None, item=None, ticker=None, delete=False):
        with self.database.transaction() as db:
            if not db.execute("SELECT 1 FROM watchlists WHERE id=?", (str(list_id),)).fetchone():
                raise KeyError("watchlist")
            if item is not None:
                db.execute(
                    """INSERT INTO watchlist_items VALUES (?,?,?,?)
                    ON CONFLICT(watchlist_id,ticker) DO UPDATE SET
                    notes=excluded.notes,tags_json=excluded.tags_json""",
                    (str(list_id), item.ticker, item.notes, json.dumps(item.tags)),
                )
            elif ticker is not None:
                db.execute(
                    "DELETE FROM watchlist_items WHERE watchlist_id=? AND ticker=?",
                    (str(list_id), ticker),
                )
            elif delete:
                db.execute("DELETE FROM watchlists WHERE id=?", (str(list_id),))
            else:
                db.execute("UPDATE watchlists SET name=? WHERE id=?", (name, str(list_id)))

    def detail(self, list_id, *, now=None):
        now = now or datetime.now(UTC)
        with closing(self.database.connect()) as db:
            row = db.execute("SELECT * FROM watchlists WHERE id=?", (str(list_id),)).fetchone()
            if row is None:
                raise KeyError("watchlist")
            items = []
            for row_item in db.execute(
                "SELECT * FROM watchlist_items WHERE watchlist_id=? ORDER BY ticker",
                (str(list_id),),
            ):
                item = dict(row_item)
                item["tags"] = json.loads(item.pop("tags_json"))
                run = db.execute(
                    """SELECT r.id,r.status,r.requested_at FROM research_runs r
                    JOIN instruments i ON i.id=r.instrument_id WHERE i.symbol=?
                    ORDER BY julianday(r.requested_at) DESC,r.id DESC LIMIT 1""",
                    (item["ticker"],),
                ).fetchone()
                item["latest_run"] = dict(run) if run else None
                item["freshness"], item["upcoming_events"] = [], []
                if run:
                    for snapshot in db.execute(
                        "SELECT * FROM research_snapshots WHERE run_id=?", (run["id"],)
                    ):
                        payload = json.loads(snapshot["payload_json"] or "{}")
                        if not isinstance(payload, dict):
                            payload = {}
                        provenance = payload.get("provenance", [])
                        dates = (
                            [
                                aware_date(p.get("retrieved_at"))
                                for p in provenance
                                if isinstance(p, dict)
                            ]
                            if isinstance(provenance, list)
                            else []
                        )
                        dates.append(aware_date(payload.get("retrieved_at")))
                        known_dates = [d for d in dates if d is not None]
                        retrieved = min(known_dates) if known_dates else None
                        age = (now - retrieved).total_seconds() if retrieved else None
                        item["freshness"].append(
                            {
                                "lane": snapshot["lane"],
                                "status": snapshot["status"],
                                "retrieved_at": retrieved.isoformat() if retrieved else None,
                                "age_seconds": age if age is not None and age >= 0 else None,
                                "state": "unknown"
                                if age is None or age < 0
                                else "stale"
                                if age > 86400
                                else "recent",
                            }
                        )
                        if snapshot["lane"] == "earnings" and snapshot["status"] == "completed":
                            data = payload.get("data", payload)
                            event = data.get("upcoming", data) if isinstance(data, dict) else None
                            if isinstance(event, dict):
                                scheduled = aware_date(event.get("scheduled_at"))
                                if scheduled and scheduled >= now:
                                    item["upcoming_events"].append(
                                        {
                                            "kind": "earnings",
                                            "scheduled_at": scheduled.isoformat(),
                                            "release_session": event.get(
                                                "exchange_session",
                                                event.get("release_session", "unknown"),
                                            ),
                                            "evidence_ids": event.get(
                                                "evidence_ids", payload.get("evidence_ids", [])
                                            ),
                                            "source_url": event.get(
                                                "source_url", payload.get("source_url")
                                            ),
                                            "retrieved_at": retrieved.isoformat()
                                            if retrieved
                                            else None,
                                        }
                                    )
                items.append(item)
        return dict(row) | {"items": items, "as_of": now.isoformat()}
