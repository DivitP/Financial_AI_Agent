"""Source-linked watchlist events from saved research, without provider requests."""

import json
from contextlib import closing
from datetime import date, datetime
from hashlib import sha256

from financial_ai.analysis.compare import ResearchComparison


def candidates(lane, payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return []
    if lane == "earnings":
        event = data.get("upcoming", data)
        return [("earnings", event)] if isinstance(event, dict) else []
    key, kind = {
        "guidance": ("events", "guidance"),
        "dividends": ("events", "dividend"),
        "macro": ("releases", "economic_release"),
        "decision": ("catalysts", "catalyst"),
    }[lane]
    values = data.get(key, [])
    return [(kind, v) for v in values if isinstance(v, dict)] if isinstance(values, list) else []


def event_date(value):
    if not isinstance(value, str):
        raise ValueError("Missing date")
    if len(value) == 10:
        day = date.fromisoformat(value)
        return day, day.isoformat(), "unknown (date only)", "date"
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError("Timestamp requires an explicit timezone offset")
    return timestamp.date(), timestamp.isoformat(), timestamp.tzname(), "timestamp"


class WatchlistCalendar:
    def __init__(self, database):
        self.database = database

    def events(self, start, end, watchlist_id=None):
        output: dict[str, dict] = {}
        limitations = []
        with closing(self.database.connect()) as db:
            if (
                watchlist_id
                and not db.execute(
                    "SELECT 1 FROM watchlists WHERE id=?", (str(watchlist_id),)
                ).fetchone()
            ):
                raise KeyError("Watchlist not found")
            tickers = [
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT ticker FROM watchlist_items WHERE (? IS NULL OR watchlist_id=?) ORDER BY ticker LIMIT 201",
                    (str(watchlist_id) if watchlist_id else None, str(watchlist_id)),
                )
            ]
            if len(tickers) > 200:
                raise ValueError("Select a watchlist with at most 200 distinct tickers")
            citations = ResearchComparison(self.database)
            for ticker in tickers:
                instruments = db.execute(
                    "SELECT id FROM instruments WHERE symbol=?", (ticker,)
                ).fetchall()
                if len(instruments) != 1:
                    limitations.append(f"{ticker}: missing or ambiguous saved instrument")
                    continue
                run = db.execute(
                    """SELECT id FROM research_runs WHERE instrument_id=?
                    AND status NOT IN ('pending','running') ORDER BY julianday(requested_at) DESC,id DESC LIMIT 1""",
                    (instruments[0]["id"],),
                ).fetchone()
                if not run:
                    limitations.append(f"{ticker}: no terminal saved research run")
                    continue
                seen = set()
                for row in db.execute(
                    "SELECT * FROM research_snapshots WHERE run_id=?", (run["id"],)
                ):
                    if row["lane"] not in (
                        "earnings",
                        "guidance",
                        "dividends",
                        "macro",
                        "decision",
                    ):
                        continue
                    seen.add(row["lane"])
                    if row["status"] != "completed":
                        limitations.append(f"{ticker}/{row['lane']}: saved lane failed")
                        continue
                    for kind, event in candidates(
                        row["lane"], json.loads(row["payload_json"] or "{}")
                    ):
                        try:
                            day, scheduled, timezone, precision = event_date(
                                event.get("scheduled_at", event.get("due_at"))
                            )
                        except (ValueError, TypeError):
                            limitations.append(
                                f"{ticker}/{kind}: undated or ambiguous event omitted"
                            )
                            continue
                        if not start <= day <= end:
                            continue
                        links = citations._citations(event, run["id"], db)
                        if not links:
                            limitations.append(
                                f"{ticker}/{kind}: event lacks exact run-scoped evidence; omitted"
                            )
                            continue
                        title = (
                            event.get("title")
                            if isinstance(event.get("title"), str)
                            else kind.replace("_", " ").title()
                        )
                        confidence = event.get("date_confidence")
                        confidence = (
                            confidence
                            if confidence in ("confirmed", "estimated", "tentative")
                            else "unknown"
                        )
                        # Confidence is source metadata, never a probability invented from source tier.
                        session = event.get("exchange_session", event.get("release_session"))
                        session = (
                            session
                            if session in ("before_market", "during_market", "after_market")
                            else "unknown"
                        )
                        signature = json.dumps(
                            [
                                kind,
                                title,
                                scheduled,
                                sorted(l["exact_url"] for l in links),
                                confidence,
                                session,
                            ]
                        )
                        key = sha256(signature.encode()).hexdigest()
                        if key not in output:
                            output[key] = {
                                "id": key,
                                "kind": kind,
                                "title": title,
                                "scheduled_at": scheduled,
                                "timezone": timezone,
                                "precision": precision,
                                "date_confidence": confidence,
                                "confidence_basis": "Saved source date-status; not forecast confidence",
                                "release_session": session,
                                "tickers": [],
                                "sources": [],
                            }
                        if ticker not in output[key]["tickers"]:
                            output[key]["tickers"].append(ticker)
                        source = {"ticker": ticker, "run_id": run["id"], "evidence": links}
                        if source not in output[key]["sources"]:
                            output[key]["sources"].append(source)
                        if len(output) > 1000:
                            raise ValueError(
                                "More than 1000 events; narrow the date range or watchlist"
                            )
                for missing in sorted(
                    {"earnings", "guidance", "dividends", "macro", "decision"} - seen
                ):
                    limitations.append(f"{ticker}/{missing}: no saved coverage")
        return {
            "events": sorted(
                output.values(), key=lambda e: (e["scheduled_at"][:10], e["scheduled_at"], e["id"])
            ),
            "limitations": limitations,
            "notice": "Saved dates only; not a live calendar. Filtering uses each source's local date. Unknown confidence stays unknown; conflicting dates remain separate.",
        }
