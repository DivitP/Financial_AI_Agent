"""Conservative comparison of stored research; never fetch or infer missing metadata."""

import json
import math
from contextlib import closing
from urllib.parse import urlsplit

from financial_ai.storage.database import Database
from financial_ai.storage.history import ResearchHistory


def normalize_metric(record):
    result = dict(record)
    value, unit = record.get("value"), record.get("unit")
    conversion = {
        "percent": ("fraction", 1),  # MetricResult stores percent as a fraction.
        "fraction": ("fraction", 1),
        "percentage_points": ("fraction", 0.01),
        "usd": ("currency", 1),
        "usd_thousands": ("currency", 1000),
        "usd_millions": ("currency", 1_000_000),
        "currency": ("currency", 1),
        "multiple": ("multiple", 1),
        "per_share": ("per_share", 1),
        "shares": ("shares", 1),
    }
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or unit not in conversion
    ):
        return result | {"normalized_value": None, "normalized_unit": None}
    normalized_unit, factor = conversion[unit]
    return result | {
        "normalized_value": value * factor,
        "normalized_unit": normalized_unit,
        "currency": "USD" if unit.startswith("usd") else record.get("currency"),
    }


def metric_records(value, path=""):
    if isinstance(value, dict):
        if "value" in value and "unit" in value:
            yield path or str(value.get("name", "metric")), value
        else:
            for key, child in sorted(value.items()):
                yield from metric_records(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, dict) and isinstance(child.get("name"), str):
                yield from metric_records(
                    child, f"{path}.{child['name']}" if path else child["name"]
                )


class ResearchComparison:
    def __init__(self, database: Database):
        self.database = database

    def compare(self, tickers):
        columns: list[dict] = []
        rows: dict[str, dict[str, dict]] = {}
        with closing(self.database.connect()) as db:
            for ticker in tickers:
                instruments = db.execute(
                    "SELECT * FROM instruments WHERE symbol=?", (ticker,)
                ).fetchall()
                column: dict = {"ticker": ticker, "run_id": None, "sections": {}, "limitations": []}
                columns.append(column)
                if len(instruments) != 1:
                    column["limitations"].append(
                        "No saved instrument"
                        if not instruments
                        else "Ambiguous saved instrument; multiple asset types/exchanges"
                    )
                    continue
                instrument = instruments[0]
                column.update(asset_type=instrument["asset_type"], currency=instrument["currency"])
                run = db.execute(
                    """SELECT * FROM research_runs WHERE instrument_id=?
                    AND status NOT IN ('pending','running')
                    ORDER BY julianday(requested_at) DESC,id DESC LIMIT 1""",
                    (instrument["id"],),
                ).fetchone()
                if not run:
                    column["limitations"].append("No terminal saved run")
                    continue
                column.update(
                    run_id=run["id"], status=run["status"], requested_at=run["requested_at"]
                )
                history = ResearchHistory(self.database).reopen(run["id"])
                if history["report"]:
                    snapshots = history["snapshots"]
                    column.update(
                        as_of=history["report"]["as_of"], version=history["report"]["version"]
                    )
                    if not snapshots:
                        column["limitations"].append(
                            "Original report snapshots unavailable; current data not substituted"
                        )
                else:
                    snapshots = [
                        dict(r) | {"payload": json.loads(r["payload_json"] or "null")}
                        for r in db.execute(
                            "SELECT * FROM research_snapshots WHERE run_id=?", (run["id"],)
                        )
                    ]
                    column["as_of"] = run["completed_at"]
                    column["limitations"].append("Stored terminal snapshots; not a frozen report")
                for snapshot in snapshots:
                    lane, payload = snapshot["lane"], snapshot["payload"]
                    if lane not in ("fundamentals", "valuation", "etf", "decision", "quality"):
                        continue
                    if instrument["asset_type"] == "etf" and lane in ("fundamentals", "valuation"):
                        continue
                    if snapshot["status"] != "completed" or payload is None:
                        column["limitations"].append(f"{lane}: unavailable or failed")
                        continue
                    if lane in ("decision", "quality"):
                        column["sections"][lane] = {
                            "data": payload,
                            "evidence": self._citations(payload, run["id"], db),
                            "comparison": "Context only; not ranked or assumed to use identical methods",
                        }
                    else:
                        for name, record in metric_records(payload):
                            key = f"{lane}.{name}"
                            cells = rows.setdefault(key, {})
                            if ticker in cells:
                                cells[ticker]["duplicate"] = True
                                continue
                            cells[ticker] = normalize_metric(record) | {
                                "evidence": self._citations(record, run["id"], db)
                            }
            output = []
            for name, cells in sorted(rows.items()):
                reasons = []
                if len(cells) != len(tickers):
                    reasons.append("Missing metric for one or more tickers")
                if len({c.get("asset_type") for c in columns}) != 1:
                    reasons.append("Different or unknown asset types")
                records = list(cells.values())
                for field in (
                    "currency",
                    "period_start",
                    "period_end",
                    "period_type",
                    "methodology",
                    "normalized_unit",
                ):
                    values = [r.get(field) for r in records]
                    if (
                        any(not isinstance(v, str) or not v for v in values)
                        or len(set(str(v) for v in values)) != 1
                    ):
                        reasons.append(f"Different or unknown {field}")
                if any(r["normalized_value"] is None or r.get("duplicate") for r in records):
                    reasons.append("Unavailable value, unsupported unit, or multiple observations")
                if any(not r["evidence"] for r in records):
                    reasons.append("Missing exact run-scoped evidence")
                output.append(
                    {"metric": name, "comparable": not reasons, "reasons": reasons, "cells": cells}
                )
        return {
            "columns": columns,
            "metrics": output,
            "notice": "Saved research only. No FX conversion, fiscal-period alignment, rankings or investment recommendations. Scenarios, risks and quality remain contextual.",
        }

    def _citations(self, payload, run_id, db):
        from financial_ai.analysis.delta import evidence_ids

        links = []
        for eid in sorted(evidence_ids(payload)):
            row = db.execute(
                "SELECT id,exact_url,provider,retrieved_at FROM evidence WHERE id=? AND run_id=?",
                (eid, run_id),
            ).fetchone()
            if row is None:
                return []
            try:
                url = urlsplit(row["exact_url"] or "")
            except ValueError:
                return []
            if url.scheme not in ("http", "https") or not url.netloc or url.path in ("", "/"):
                return []
            links.append(dict(row))
        return links
