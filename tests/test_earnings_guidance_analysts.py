from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from financial_ai.analysis.analysts import (
    PUBLIC_CONSENSUS_LABEL,
    PublicAnalystConsensus,
    RecommendationDistribution,
)
from financial_ai.analysis.earnings import (
    ExchangeSession,
    ReleaseSession,
    price_reaction,
    revision_direction,
)
from financial_ai.analysis.guidance import GuidanceOrigin, GuidanceStatement, compare_guidance


def test_earnings_release_sessions_use_exchange_calendar_times() -> None:
    ny = ZoneInfo("America/New_York")
    session = ExchangeSession(
        "NASDAQ", datetime(2026, 8, 20, 9, 30, tzinfo=ny), datetime(2026, 8, 20, 16, 0, tzinfo=ny)
    )
    assert session.classify(datetime(2026, 8, 20, 8, 0, tzinfo=ny)) is ReleaseSession.BEFORE_MARKET
    assert session.classify(datetime(2026, 8, 20, 16, 1, tzinfo=ny)) is ReleaseSession.AFTER_MARKET
    assert session.classify(datetime(2026, 8, 20, 12, 0, tzinfo=ny)) is ReleaseSession.DURING_MARKET
    with pytest.raises(ValueError, match="timezone"):
        session.classify(datetime(2026, 8, 20, 8, 0))
    assert price_reaction(Decimal("100"), Decimal("105")) == Decimal("0.05")
    assert revision_direction(Decimal("1.20"), Decimal("1.10")) == "down"


def test_explicit_guidance_requires_cited_wording_and_inference_stays_separate() -> None:
    with pytest.raises(ValueError, match="cited wording"):
        GuidanceStatement(
            "revenue",
            "FY26",
            Decimal("100"),
            Decimal("110"),
            "USD millions",
            GuidanceOrigin.EXPLICIT_MANAGEMENT,
            uuid4(),
        )
    explicit = GuidanceStatement(
        "revenue",
        "FY26",
        Decimal("100"),
        Decimal("110"),
        "USD millions",
        GuidanceOrigin.EXPLICIT_MANAGEMENT,
        uuid4(),
        "We expect revenue of $100–$110 million.",
    )
    previous = GuidanceStatement(
        "revenue",
        "FY25",
        Decimal("90"),
        Decimal("100"),
        "USD millions",
        GuidanceOrigin.INFERRED,
        uuid4(),
    )
    comparison = compare_guidance(explicit, previous, Decimal("112"))
    assert comparison.change_direction == "raised"
    assert comparison.result_position == "above"


def test_public_consensus_exposes_target_dispersion_and_not_proprietary_research() -> None:
    consensus = PublicAnalystConsensus(
        datetime(2026, 8, 20, tzinfo=ZoneInfo("UTC")),
        RecommendationDistribution(strong_buy=3, buy=4, hold=2),
        Decimal("200"),
        Decimal("150"),
        Decimal("250"),
        9,
        "up",
    )
    assert consensus.recommendations.total == 9
    assert consensus.target_dispersion == Decimal("0.5")
    assert "not proprietary" in PUBLIC_CONSENSUS_LABEL.lower()
