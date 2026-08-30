from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from financial_ai.analysis.macro import (
    CompanyExposure,
    Exposure,
    build_macro_context,
    select_macro_series,
)
from financial_ai.analysis.positioning import (
    DataTimeliness,
    LiquiditySnapshot,
    OptionsStatistics,
    ShortInterest,
    build_positioning_context,
)
from financial_ai.providers.contracts import MacroObservation


NOW = datetime(2026, 8, 30, tzinfo=UTC)


def test_macro_selection_only_attaches_series_justified_by_company_exposure() -> None:
    exposure = CompanyExposure(
        "Airlines",
        frozenset({Exposure.COMMODITY, Exposure.CURRENCY, Exposure.INDUSTRY}),
        ("DCOILWTICO",),
        ("DEXUSEU",),
        ("AIRPASSENGERS",),
    )
    selected = select_macro_series(exposure)
    assert {item.series_id for item in selected} == {"DCOILWTICO", "DEXUSEU", "AIRPASSENGERS"}
    observations = [
        MacroObservation(series_id="DCOILWTICO", observed_at=NOW, value=Decimal("80"), unit="USD"),
        MacroObservation(series_id="CPIAUCSL", observed_at=NOW, value=Decimal("300"), unit="index"),
    ]
    assert [
        item.series_id for item in build_macro_context(exposure, observations).observations
    ] == ["DCOILWTICO"]


def test_positioning_context_marks_delayed_and_incomplete_inputs_honestly() -> None:
    options = OptionsStatistics(
        NOW,
        DataTimeliness.INCOMPLETE,
        implied_volatility=Decimal("0.35"),
        missing_fields=("put_call_open_interest_ratio",),
    )
    short_interest = ShortInterest(
        NOW - timedelta(days=20),
        NOW - timedelta(days=16),
        DataTimeliness.DELAYED,
        Decimal("1000000"),
        Decimal("0.12"),
        Decimal("3"),
    )
    liquidity = LiquiditySnapshot(
        NOW,
        DataTimeliness.CURRENT,
        Decimal("200"),
        Decimal("100"),
        Decimal("99"),
        Decimal("101"),
        Decimal("100"),
    )
    context = build_positioning_context(options, short_interest, liquidity, as_of=NOW)
    assert liquidity.relative_volume == Decimal("2") and liquidity.quoted_spread_bps == Decimal(
        "200"
    )
    assert any("incomplete" in warning.lower() for warning in context.warnings)
    assert any("delay exceeds" in warning.lower() for warning in context.warnings)
