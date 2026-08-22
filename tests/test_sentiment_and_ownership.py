from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from financial_ai.analysis.ownership import (
    OwnershipActivity,
    OwnershipEventType,
    classify_form4,
    classify_ownership_form,
)
from financial_ai.analysis.sentiment import (
    EventCategory,
    LocalFinanceSentiment,
    summarize_sentiment,
)
from financial_ai.providers.news import NewsArticle, NewsSource


NOW = datetime(2026, 8, 21, tzinfo=UTC)


def test_local_finance_sentiment_has_span_confidence_uncertainty_events_and_time_decay() -> None:
    article = NewsArticle(
        canonical_url="https://example.test/a",
        publisher="Company IR",
        title="Company raises guidance after earnings",
        summary="Management increased its outlook.",
        published_at=NOW - timedelta(days=7),
        retrieved_at=NOW,
        source=NewsSource.COMPANY_IR,
    )
    model = LocalFinanceSentiment(lambda _: [{"label": "positive", "score": 0.9}])
    result = model.analyze(article, as_of=NOW)
    assert result.text_span.startswith("Company raises guidance")
    assert result.confidence == 0.9 and result.uncertainty == pytest.approx(0.1)
    assert (
        EventCategory.EARNINGS in result.event_categories
        and EventCategory.GUIDANCE in result.event_categories
    )
    assert 0 < result.time_decay < 1
    summary = summarize_sentiment([result, result])
    assert summary.score == 1 and summary.source_diversity == 0.5


def test_ownership_activity_exposes_type_and_reporting_delay() -> None:
    filed = NOW
    sale = OwnershipActivity(
        "4",
        "Director",
        classify_form4("S", "D", planned=True),
        NOW - timedelta(days=2),
        filed,
        Decimal("100"),
        planned=True,
    )
    assert sale.event_type is OwnershipEventType.PLANNED_SALE
    assert sale.reporting_delay_days == 2
    assert classify_form4("A", "A") is OwnershipEventType.GRANT
    assert classify_form4("P", "A") is OwnershipEventType.PURCHASE
    assert classify_form4("D", "D") is OwnershipEventType.DISPOSITION
    assert classify_ownership_form("SC 13G/A") is OwnershipEventType.BENEFICIAL_OWNERSHIP_CHANGE
    assert classify_ownership_form("13F-HR") is OwnershipEventType.INSTITUTIONAL_HOLDING_CHANGE
