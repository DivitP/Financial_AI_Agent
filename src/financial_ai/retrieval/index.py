"""Rebuildable source-aware indexes; relational evidence is never modified."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, AwareDatetime

from financial_ai.storage.database import Database


class SourceText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,14}$")
    run_id: UUID
    evidence_id: UUID
    source_url: HttpUrl
    kind: Literal["filing", "release", "article", "report"]
    period: str
    published_at: AwareDatetime
    retrieved_at: AwareDatetime
    text: str = Field(min_length=1, max_length=2_000_000)


def safe_text(text: str) -> None:
    """Reject common credential/binary/chart payloads, never silently redact evidence."""
    if re.search(
        r"data:|base64|<svg|<img|-----BEGIN|\b(?:sk-|gsk_)[\w-]+|"
        r"(?:api[_ -]?key|password|secret|authorization|token)\s*[:=]|"
        r"[A-Za-z0-9+/]{100,}={0,2}|[\x00-\x08]|\b(?:ohlcv|chart_data)\b",
        text,
        re.I,
    ):
        raise ValueError("Document contains excluded binary, chart, or credential content")


def chunks(source: SourceText, max_chars: int = 1200) -> list[dict[str, str]]:
    if not 100 <= max_chars <= 4000:
        raise ValueError("max_chars must be between 100 and 4000")
    safe_text(source.text)
    safe_text(str(source.source_url))
    metadata = source.model_dump(mode="json", exclude={"text"})
    for value in metadata.values():
        safe_text(str(value))
    metadata["source_hash"] = hashlib.sha256(source.text.encode()).hexdigest()
    section = "Document"
    result = {}
    for block in re.split(r"\n\s*\n|(?=^#{1,6} |^Item \d)", source.text, flags=re.M):
        block = block.strip()
        if not block:
            continue
        if re.match(r"^(#{1,6} |Item \d)", block):
            heading, _, block = block.partition("\n")
            section = heading.lstrip("# ")
        for offset in range(0, len(block), max_chars):
            text = block[offset : offset + max_chars].strip()
            if not text:
                continue
            digest = hashlib.sha256(text.encode()).hexdigest()
            identity = f"{source.run_id}|{source.ticker}|{source.evidence_id}|{metadata['source_hash']}|{digest}"
            key = hashlib.sha256(identity.encode()).hexdigest()
            result[key] = dict(metadata, id=key, text=text, section=section, content_hash=digest)
    return list(result.values())


class VectorIndex(Protocol):
    def upsert(self, records: list[dict[str, str]]) -> None: ...
    def search(self, query: str, filters: dict[str, str], limit: int) -> list[str]: ...


class ResearchIndex:
    """SQLite FTS cache with best-effort vector replication and repair by reindexing."""

    def __init__(self, sources: Database, path: Path, vector: VectorIndex | None = None):
        if path.resolve() == sources.path.resolve():
            raise ValueError("Index must be separate from source database")
        self.sources, self.path, self.vector = sources, path, vector
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, metadata TEXT NOT NULL)"
            )
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, text)"
            )

    def index(self, source: SourceText) -> list[str]:
        with closing(self.sources.connect()) as db:
            row = db.execute(
                "SELECT e.exact_url FROM evidence e JOIN research_runs r ON r.id=e.run_id "
                "JOIN instruments i ON i.id=r.instrument_id WHERE e.id=? AND e.run_id=? AND i.symbol=?",
                (str(source.evidence_id), str(source.run_id), source.ticker),
            ).fetchone()
        if row is None or row["exact_url"] != str(source.source_url):
            raise ValueError("Source does not match relational evidence, run, ticker and URL")
        records = chunks(source)
        with closing(sqlite3.connect(self.path)) as db, db:
            for record in records:
                inserted = db.execute(
                    "INSERT OR IGNORE INTO chunks VALUES (?, ?)", (record["id"], json.dumps(record))
                ).rowcount
                if inserted:
                    db.execute(
                        "INSERT INTO chunks_fts VALUES (?, ?)", (record["id"], record["text"])
                    )
        if self.vector and records:
            try:
                self.vector.upsert(records)
            except Exception:
                return [
                    "Semantic indexing failed; lexical index remains available. Retry indexing to repair."
                ]
        return []

    def search(
        self,
        query: str,
        *,
        ticker: str,
        run_id: UUID,
        as_of: datetime,
        kind: str | None = None,
        period: str | None = None,
        limit: int = 10,
        half_life_days: float = 90,
    ) -> tuple[list[dict[str, str]], list[str]]:
        if not 1 <= limit <= 100 or half_life_days <= 0 or as_of.utcoffset() is None:
            raise ValueError("Invalid retrieval limits or as-of date")
        filters = {"ticker": ticker, "run_id": str(run_id)}
        filters.update({k: v for k, v in {"kind": kind, "period": period}.items() if v is not None})
        with closing(sqlite3.connect(self.path)) as db:
            records = {
                key: json.loads(raw) for key, raw in db.execute("SELECT id, metadata FROM chunks")
            }
            allowed = {
                key: r
                for key, r in records.items()
                if all(r[k] == v for k, v in filters.items())
                and datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")) <= as_of
                and datetime.fromisoformat(r["retrieved_at"].replace("Z", "+00:00")) <= as_of
            }
            tokens = re.findall(r"\w+", query)[:40]
            if not tokens:
                return [], []
            expression = " OR ".join('"' + token + '"' for token in tokens)
            lexical = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts)",
                    (expression,),
                )
                if row[0] in allowed
            ][: limit * 4]
        warnings, semantic = [], []
        if self.vector:
            try:
                semantic = self.vector.search(query, filters, limit * 4)
            except Exception:
                warnings.append("Semantic search unavailable; using lexical results.")
        scores: dict[str, float] = {}
        for ranking in (lexical, semantic):
            for rank, key in enumerate(dict.fromkeys(ranking), 1):
                if key in allowed:
                    scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        for key in scores:
            age = (
                as_of - datetime.fromisoformat(allowed[key]["published_at"].replace("Z", "+00:00"))
            ).total_seconds() / 86400
            scores[key] *= 0.5 + 0.5 * 2 ** (-age / half_life_days)
        return [
            allowed[key] for key in sorted(scores, key=lambda k: (-scores[k], k))[:limit]
        ], warnings
