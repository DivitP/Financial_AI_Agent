from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from financial_ai.domain.models import EvidenceKind, Freshness, MetricObservation, SourceTier
from financial_ai.evidence import EvidenceNormalizer
from financial_ai.providers.sec import SecFilingCollector, sec_document_url


FIXTURES = Path(__file__).parent / "fixtures/sec"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_sec_cik_mapping_and_accession_urls_from_fixtures() -> None:
    collector = SecFilingCollector()
    companies = collector.companies(_fixture("company_tickers.json"))
    filings = collector.filings(companies["AAPL"].cik, _fixture("submissions.json"))

    assert companies["AAPL"].cik == "0000320193"
    assert [filing.form for filing in filings] == ["10-K", "8-K"]
    assert (
        filings[0].url
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/aapl-20250927.htm"
    )
    assert sec_document_url("0000320193", "0000320193-26-000002", "aapl-8k.htm") == filings[1].url


def test_sec_xbrl_keeps_restated_facts_distinct() -> None:
    facts = SecFilingCollector().xbrl_facts(uuid4(), _fixture("companyfacts.json"))
    revenues = [fact for fact in facts if fact.tag == "Revenues"]

    assert len(revenues) == 2
    assert revenues[0].identity != revenues[1].identity
    assert revenues[0].period_end == revenues[1].period_end
    assert revenues[1].form == "10-K/A"


def test_evidence_normalization_is_stable_and_has_exact_url() -> None:
    normalizer = EvidenceNormalizer()
    run_id = uuid4()
    first = normalizer.normalize(
        run_id=run_id,
        provider="sec",
        kind=EvidenceKind.FILING,
        exact_url="https://www.sec.gov/Archives/edgar/data/320193/example.htm",
        title="Apple 10-K",
        content="Revenue was reported in the filing.",
        retrieved_at=datetime(2026, 8, 14, tzinfo=UTC),
        published_at=datetime(2026, 8, 12, tzinfo=UTC),
        source_tier=SourceTier.PRIMARY,
    )
    second = normalizer.normalize(
        run_id=run_id,
        provider="sec",
        kind=EvidenceKind.FILING,
        exact_url="https://www.sec.gov/Archives/edgar/data/320193/example.htm",
        title="Apple 10-K",
        content="Revenue was reported in the filing.",
        retrieved_at=datetime(2026, 8, 14, tzinfo=UTC),
        published_at=datetime(2026, 8, 12, tzinfo=UTC),
        source_tier=SourceTier.PRIMARY,
    )

    assert first.evidence.id == second.evidence.id
    assert first.evidence.content_hash == second.evidence.content_hash
    assert (
        str(first.evidence.exact_url)
        == "https://www.sec.gov/Archives/edgar/data/320193/example.htm"
    )
    assert first.evidence.freshness == Freshness.FRESH


def test_metric_cannot_exist_without_a_valid_evidence_id() -> None:
    with pytest.raises(ValidationError, match="evidence_id"):
        MetricObservation(
            id=uuid4(),
            run_id=uuid4(),
            instrument_id=uuid4(),
            metric_name="revenue",
            value=1.0,
            unit="USD",
            observed_at=datetime(2026, 8, 14, tzinfo=UTC),
            provider="sec",
            evidence_id="missing",
        )
