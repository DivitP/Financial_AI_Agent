from datetime import UTC, datetime
from uuid import uuid4

import pytest

from financial_ai.domain.models import AssetType, Evidence, EvidenceKind, Instrument, ResearchRun
from financial_ai.storage import Database, ResearchRepository
from financial_ai.retrieval.index import ResearchIndex, SourceText, chunks


NOW = datetime(2026, 9, 4, tzinfo=UTC)


def test_real_chroma_persists_and_filters_without_model_download(tmp_path):
    pytest.importorskip("chromadb")
    from financial_ai.retrieval.vector import ChromaIndex

    class FixtureEmbeddings:
        def encode(self, texts):
            return [[1.0, 0.0, 0.5] for _ in texts]

    db = Database(tmp_path / "source.db")
    db.migrate_to_latest()
    first, other = source(db, "AAPL"), source(db, "MSFT")
    vector = ChromaIndex(tmp_path / "chroma", FixtureEmbeddings(), model_version="fixture-v1")
    vector.upsert(chunks(first) + chunks(other))
    vector.upsert(chunks(first))
    reopened = ChromaIndex(tmp_path / "chroma", FixtureEmbeddings(), model_version="fixture-v1")
    assert reopened.collection.count() == 4
    ids = reopened.search("Revenue", {"ticker": "AAPL", "run_id": str(first.run_id)}, 10)
    assert set(ids) == {r["id"] for r in chunks(first)}


def source(db, ticker):
    repo = ResearchRepository(db)
    instrument = Instrument(id=uuid4(), symbol=ticker, currency="USD", asset_type=AssetType.EQUITY)
    with db.connect() as connection:
        exists = connection.execute(
            "SELECT id FROM instruments WHERE symbol=?", (ticker,)
        ).fetchone()
    if exists is None:
        repo.add_instrument(instrument)
    # Reuse existing instrument when exercising two runs of the same ticker.
    with db.connect() as connection:
        row = connection.execute("SELECT id FROM instruments WHERE symbol=?", (ticker,)).fetchone()
    from uuid import UUID

    run = ResearchRun(
        id=uuid4(), instrument_id=UUID(row["id"]), requested_at=NOW, provider_config_version="test"
    )
    repo.add_run(run)
    evidence = Evidence(
        id=uuid4(),
        run_id=run.id,
        provider="sec",
        kind=EvidenceKind.FILING,
        retrieved_at=NOW,
        locator=str(uuid4()),
        content_hash="fixture",
        exact_url="https://example.com/filing",
    )
    repo.add_evidence(evidence)
    return SourceText(
        ticker=ticker,
        run_id=run.id,
        evidence_id=evidence.id,
        source_url=evidence.exact_url,
        kind="filing",
        period="2026",
        published_at=NOW,
        retrieved_at=NOW,
        text="# Risks\nRevenue faces pressure.\n\n# Results\nMargins improved.",
    )


class BrokenVector:
    def upsert(self, records):
        raise RuntimeError("embedding failed")

    def search(self, query, filters, limit):
        raise RuntimeError("search failed")


def test_failure_restart_dedup_and_source_integrity(tmp_path):
    db = Database(tmp_path / "sources.db")
    db.migrate_to_latest()
    document = source(db, "AAPL")
    index = ResearchIndex(db, tmp_path / "fts.db", BrokenVector())
    assert index.index(document)
    index.index(document)
    restarted = ResearchIndex(db, tmp_path / "fts.db", BrokenVector())
    hits, warnings = restarted.search("Revenue", ticker="AAPL", run_id=document.run_id, as_of=NOW)
    assert len(hits) == 1 and warnings
    assert hits[0]["section"] == "Risks"
    assert ResearchRepository(db).count("evidence") == 1


def test_fusion_includes_semantic_only_match_and_honors_as_of(tmp_path):
    db = Database(tmp_path / "sources.db")
    db.migrate_to_latest()
    document = source(db, "AAPL")
    records = chunks(document)

    class SemanticFixture:
        def upsert(self, records):
            pass

        def search(self, query, filters, limit):
            return [records[1]["id"], records[0]["id"]]

    index = ResearchIndex(db, tmp_path / "fts.db", SemanticFixture())
    index.index(document)
    hits, _ = index.search("Revenue", ticker="AAPL", run_id=document.run_id, as_of=NOW)
    assert [r["id"] for r in hits] == [records[0]["id"], records[1]["id"]]
    from datetime import timedelta

    assert (
        index.search(
            "Revenue", ticker="AAPL", run_id=document.run_id, as_of=NOW - timedelta(days=1)
        )[0]
        == []
    )


def test_cross_ticker_and_run_results_are_discarded(tmp_path):
    db = Database(tmp_path / "sources.db")
    db.migrate_to_latest()
    first, other = source(db, "AAPL"), source(db, "MSFT")
    index = ResearchIndex(db, tmp_path / "fts.db")
    index.index(first)
    index.index(other)
    another_run = source(db, "AAPL")
    index.index(another_run)

    class LeakyVector:
        def upsert(self, records):
            pass

        def search(self, query, filters, limit):
            return [r["id"] for r in chunks(other)]

    index.vector = LeakyVector()
    hits, _ = index.search("Revenue", ticker="AAPL", run_id=first.run_id, as_of=NOW)
    assert len(hits) == 1 and hits[0]["run_id"] == str(first.run_id)
    assert index.search("Revenue", ticker="AAPL", run_id=other.run_id, as_of=NOW)[0] == []
    assert (
        index.search("Revenue", ticker="AAPL", run_id=first.run_id, as_of=NOW, period="2025")[0]
        == []
    )


@pytest.mark.parametrize(
    "text", ["data:image/png;base64,abc", "api_key=secret", "<svg>chart</svg>", "A" * 200]
)
def test_excluded_payloads_never_enter_indexes(tmp_path, text):
    db = Database(tmp_path / "sources.db")
    db.migrate_to_latest()
    document = source(db, "AAPL").model_copy(update={"text": text})
    index = ResearchIndex(db, tmp_path / "fts.db")
    with pytest.raises(ValueError, match="excluded"):
        index.index(document)
    assert index.search("Revenue", ticker="AAPL", run_id=document.run_id, as_of=NOW)[0] == []
