"""Deterministic, citation-gated comparison of saved research, never live data."""

import json
from contextlib import closing
from urllib.parse import urlsplit

from financial_ai.storage.database import Database
from financial_ai.storage.history import ResearchHistory


LANES = (
    "filings",
    "earnings",
    "guidance",
    "analysts",
    "sentiment",
    "valuation",
    "technical",
    "decision",
)
METADATA = {
    "evidence_id",
    "evidence_ids",
    "retrieved_at",
    "updated_at",
    "created_at",
    "provenance",
    "source_url",
    "exact_url",
    "content_hash",
    "run_id",
}


def canonical(value):
    """Ignore retrieval bookkeeping and list order, not units, dates or limitations."""
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items()) if k not in METADATA}
    if isinstance(value, list):
        return sorted((canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def evidence_ids(value):
    ids = set()
    if isinstance(value, dict):
        if isinstance(value.get("evidence_id"), str):
            ids.add(value["evidence_id"])
        if isinstance(value.get("evidence_ids"), list):
            ids.update(v for v in value["evidence_ids"] if isinstance(v, str))
        for v in value.values():
            ids.update(evidence_ids(v))
    elif isinstance(value, list):
        for v in value:
            ids.update(evidence_ids(v))
    return ids


class ResearchDelta:
    def __init__(self, database: Database):
        self.database = database

    def compare(self, run_id, previous_run_id=None):
        with closing(self.database.connect()) as db:
            current = db.execute(
                "SELECT * FROM research_runs WHERE id=?", (str(run_id),)
            ).fetchone()
            if current is None:
                raise KeyError("Research run not found")
            if current["status"] in ("pending", "running"):
                raise ValueError("Finish or cancel the run before comparing saved results")
            previous = db.execute(
                """SELECT * FROM research_runs WHERE instrument_id=?
                AND julianday(requested_at)<julianday(?) AND status NOT IN ('pending','running')
                AND (? IS NULL OR id=?) ORDER BY julianday(requested_at) DESC,id DESC LIMIT 1""",
                (
                    current["instrument_id"],
                    current["requested_at"],
                    str(previous_run_id) if previous_run_id else None,
                    str(previous_run_id),
                ),
            ).fetchone()
            if previous_run_id and previous is None:
                raise ValueError("Baseline must be an earlier terminal run of the same instrument")
            result: dict = {
                "current_run_id": str(run_id),
                "previous_run_id": previous["id"] if previous else None,
                "changes": [],
                "limitations": [],
                "unchanged": [],
                "basis": {},
            }
            if previous is None:
                result["limitations"].append(
                    "No earlier completed, failed or cancelled run exists for this instrument."
                )
                return result
            old = self._saved(previous, db, result)
            new = self._saved(current, db, result)
            for lane in LANES:
                before, after = old.get(lane), new.get(lane)
                if before is None or after is None:
                    result["limitations"].append(
                        f"{lane}: missing, failed, or uncaptured lane on one or both sides; not evidence of removal."
                    )
                    continue
                if canonical(before) == canonical(after):
                    result["unchanged"].append(lane)
                    continue
                # Whole-lane comparison avoids inventing record alignment or arithmetic across periods/units.
                old_links = self._links(before, previous["id"], db)
                new_links = self._links(after, current["id"], db)
                if not old_links or not new_links:
                    result["limitations"].append(
                        f"{lane}: differing saved content cannot be verified against evidence on both sides."
                    )
                    continue
                result["changes"].append(
                    {
                        "lane": lane,
                        "kind": "saved_content_changed",
                        "old": canonical(before),
                        "new": canonical(after),
                        "old_evidence": old_links,
                        "new_evidence": new_links,
                    }
                )
            result["limitations"].append(
                "Differences describe saved content, not causal conclusions or investment signals. Coverage, periods, units and methods may differ; inspect both sides."
            )
            return result

    def _saved(self, run, db, result):
        saved = ResearchHistory(self.database).reopen(run["id"])
        if saved["report"]:
            snapshots = saved["snapshots"]
            result["basis"][run["id"]] = {
                "kind": "frozen_report",
                "version": saved["report"]["version"],
                "as_of": saved["report"]["as_of"],
            }
            if not snapshots:
                result["limitations"].append(
                    f"{run['id']}: original report snapshots unavailable; current data was not substituted."
                )
        else:
            snapshots = [
                dict(r) | {"payload": json.loads(r["payload_json"] or "null")}
                for r in db.execute("SELECT * FROM research_snapshots WHERE run_id=?", (run["id"],))
            ]
            result["basis"][run["id"]] = {
                "kind": "stored_terminal_run",
                "as_of": run["completed_at"],
                "requested_at": run["requested_at"],
            }
        return {
            s["lane"]: s["payload"]
            for s in snapshots
            if s["status"] == "completed" and s["payload"] is not None
        }

    def _links(self, payload, run_id, db):
        ids = evidence_ids(payload)
        if not ids:
            return []
        links = []
        for evidence_id in sorted(ids):
            evidence = db.execute(
                "SELECT id,exact_url,provider,retrieved_at FROM evidence WHERE id=? AND run_id=?",
                (evidence_id, run_id),
            ).fetchone()
            if evidence is None:
                return []  # Invalid or cross-run evidence blocks the whole comparison.
            url = urlsplit(evidence["exact_url"] or "")
            if url.scheme not in ("http", "https") or not url.netloc or url.path in ("", "/"):
                return []
            links.append(dict(evidence))
        return links
