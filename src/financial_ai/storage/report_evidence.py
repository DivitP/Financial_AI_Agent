"""Immutable, report-scoped source passages for the Flask compatibility UI."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from financial_ai.data.documents import document_text, UnsafeDocument
from financial_ai.providers.legacy_live import symbol
from financial_ai.security import safe_link


class ReportScopeError(ValueError):
    pass


class ReportEvidenceStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, ticker TEXT NOT NULL, created_at TEXT NOT NULL,
                    finalized INTEGER NOT NULL DEFAULT 0, markdown TEXT NOT NULL DEFAULT '',
                    options TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES reports(id),
                    ticker TEXT NOT NULL, metadata TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS passages (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
                    report_id TEXT NOT NULL REFERENCES reports(id), ticker TEXT NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS passage_search USING fts5(id UNINDEXED, content);
                CREATE INDEX IF NOT EXISTS passage_scope ON passages(report_id, ticker);
                CREATE TABLE IF NOT EXISTS answers (
                    id INTEGER PRIMARY KEY, report_id TEXT NOT NULL REFERENCES reports(id),
                    ticker TEXT NOT NULL, question TEXT NOT NULL, response TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def create(self, ticker: str) -> str:
        report_id = str(uuid4())
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO reports(id,ticker,created_at) VALUES(?,?,?)",
                (report_id, symbol(ticker), datetime.now(UTC).isoformat()),
            )
        return report_id

    def report(self, report_id, ticker, *, finalized=True):
        try:
            report_id, ticker = str(UUID(str(report_id))), symbol(ticker)
        except (ValueError, TypeError):
            raise ReportScopeError(
                "Generate or reopen a report before asking about its sources."
            ) from None
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT * FROM reports WHERE id=? AND ticker=?", (report_id, ticker)
            ).fetchone()
        if row is None or (finalized and not row["finalized"]):
            raise ReportScopeError(
                "The selected report does not match this ticker or is not complete."
            )
        return dict(row)

    def add_source(self, report_id, ticker, metadata: dict, paragraphs=()):
        self.report(report_id, ticker, finalized=False)
        if not safe_link(metadata.get("url")):
            raise ValueError("An exact safe source URL is required")
        if metadata.get("status") != "read" and paragraphs:
            raise ValueError("Unread source text cannot be indexed")
        source_id = str(uuid4())
        chunks = []
        try:
            document_text(json.dumps(metadata))
            paragraphs = list(dict.fromkeys(document_text(p).strip() for p in paragraphs))
        except UnsafeDocument:
            metadata = {**metadata, "status": "quarantined"}
            paragraphs = []
        for paragraph_index, clean in enumerate(paragraphs):
            # Stable text offsets avoid model-created IDs; every quoted span must
            # match a persisted passage, not a generated summary or feed headline.
            for start in range(0, len(clean), 1200):
                value = clean[start : start + 1200].strip()
                if value:
                    ident = hashlib.sha256(
                        f"{report_id}|{source_id}|{paragraph_index}|{start}|{value}".encode()
                    ).hexdigest()
                    chunks.append((ident, source_id, report_id, symbol(ticker), value))
        with closing(self.connect()) as db, db:
            if db.execute("SELECT finalized FROM reports WHERE id=?", (report_id,)).fetchone()[0]:
                raise ReportScopeError(
                    "Finalized report evidence is immutable; create a new report."
                )
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?)",
                (source_id, report_id, symbol(ticker), json.dumps(metadata)),
            )
            db.executemany("INSERT INTO passages VALUES(?,?,?,?,?)", chunks)
            db.executemany(
                "INSERT INTO passage_search VALUES(?,?)", [(c[0], c[-1]) for c in chunks]
            )
        return source_id

    def finalize(self, report_id, ticker, markdown, options=None):
        self.report(report_id, ticker, finalized=False)
        with closing(self.connect()) as db, db:
            changed = db.execute(
                "UPDATE reports SET finalized=1,markdown=?,options=? WHERE id=? AND ticker=? AND finalized=0",
                (markdown, json.dumps(options or {}), report_id, symbol(ticker)),
            )
            if changed.rowcount != 1:
                raise ReportScopeError("Report is already finalized")

    def sources(self, report_id, ticker):
        self.report(report_id, ticker)
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT id,metadata FROM sources WHERE report_id=? AND ticker=?",
                (report_id, symbol(ticker)),
            ).fetchall()
        return [dict(id=r["id"], **json.loads(r["metadata"])) for r in rows]

    def search(self, report_id, ticker, question, *, news=False, limit=8):
        self.report(report_id, ticker)
        tokens = [
            w
            for w in re.findall(r"[A-Za-z0-9]{3,}", question)
            if w.lower()
            not in {
                "the",
                "and",
                "what",
                "does",
                "this",
                "that",
                "about",
                "are",
                "with",
                "from",
                "for",
                "how",
                "why",
                "can",
                "tell",
                "please",
                "filing",
                "article",
                "news",
                "say",
                "says",
                "source",
                "original",
                "report",
                "show",
                "shows",
                "recent",
                "latest",
                symbol(ticker).lower(),
            }
        ][:20]
        query = " OR ".join('"' + t + '"' for t in tokens)
        # Scope predicates are in SQL, before ranking and LIMIT. There is no
        # fallback to another report, another ticker or an old unscoped index.
        sql = """SELECT p.id,p.content,s.metadata FROM passages p
                 JOIN sources s ON s.id=p.source_id
                 JOIN passage_search ON passage_search.id=p.id
                 WHERE p.report_id=? AND p.ticker=?"""
        params: list = [report_id, symbol(ticker)]
        if news:
            sql += " AND json_extract(s.metadata,'$.kind') IN ('article','filing')"
        with closing(self.connect()) as db:
            rows = []
            if query:
                rows = db.execute(
                    sql + " AND passage_search MATCH ? ORDER BY bm25(passage_search) LIMIT ?",
                    [*params, query.replace(" OR ", " AND "), limit * 4],
                ).fetchall()
                if not rows:
                    rows = db.execute(
                        sql + " AND passage_search MATCH ? ORDER BY bm25(passage_search) LIMIT ?",
                        [*params, query, limit * 4],
                    ).fetchall()
            if not rows and news:
                rows = db.execute(
                    sql + " ORDER BY p.rowid LIMIT ?", [*params, limit * 4]
                ).fetchall()
        # Cap each source's contribution so one long article cannot crowd out
        # other coverage. Metadata comes only from persisted source records.
        result = []
        counts: dict[str, int] = {}
        for row in rows:
            meta = json.loads(row["metadata"])
            url = meta["url"]
            if counts.get(url, 0) >= 3:
                continue
            counts[url] = counts.get(url, 0) + 1
            result.append(dict(id=row["id"], text=row["content"], **meta))
            if len(result) == limit:
                break
        return result

    def save_answer(self, report_id, ticker, question, response):
        self.report(report_id, ticker)
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO answers(report_id,ticker,question,response,created_at) VALUES(?,?,?,?,?)",
                (
                    report_id,
                    symbol(ticker),
                    question,
                    json.dumps(response),
                    datetime.now(UTC).isoformat(),
                ),
            )
