from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from financial_ai.analysis.etf import ETFHolding, ETFProfile, analyze_etf, research_sections
from financial_ai.analysis.quality import QualityClaim, QualityRecord, assess_data_quality
from financial_ai.analysis.technical import PricePoint, analyze_technical_regime
from financial_ai.domain.models import AssetType


NOW = datetime(2026, 8, 30, tzinfo=UTC)


def test_etf_path_excludes_corporate_earnings_and_reports_concentration() -> None:
    sections = research_sections(AssetType.ETF)
    assert "earnings" not in sections and "holdings" in sections
    report = analyze_etf(
        ETFProfile(
            Decimal("0.0009"),
            (
                ETFHolding("AAPL", "Apple", Decimal("0.20"), "Technology"),
                ETFHolding("MSFT", "Microsoft", Decimal("0.15"), "Technology"),
            ),
            Decimal("1000000"),
            Decimal("-0.001"),
        )
    )
    assert report.top_ten_weight == Decimal("0.35") and report.concentration_hhi == Decimal(
        "0.0625"
    )
    assert report.constituent_risks


def test_data_quality_grade_has_reasons_not_global_confidence() -> None:
    evidence = uuid4()
    report = assess_data_quality(
        as_of=NOW,
        required_lanes=("quote", "statements", "news"),
        completed_lanes=("quote",),
        records=(
            QualityRecord("period_current", NOW - timedelta(days=45), "provider_a", 10.0, "new"),
            QualityRecord("period_current", NOW, "provider_b", 11.0, "old"),
        ),
        claims=(QualityClaim("Unsupported conclusion", (uuid4(),)),),
        evidence_ids=frozenset({evidence}),
    )
    assert report.grade.value in {"C", "D"}
    assert any("Incomplete" in reason for reason in report.reasons)
    assert any("Unsupported" in reason for reason in report.reasons)


def test_technical_regime_describes_conditions_without_trade_commands() -> None:
    points = [
        PricePoint(NOW + timedelta(days=index), 100 + index * 2, 1000 + index * 100)
        for index in range(25)
    ]
    result = analyze_technical_regime(points)
    assert result.trend == "uptrend" and result.regime == "trending"
    assert result.support == 110 and result.resistance == 148
    assert (
        "buy"
        not in " ".join(
            vars(result).values() if False else [result.trend, result.momentum, result.regime]
        ).lower()
    )
