from __future__ import annotations

from financial_ai.analysis.fundamentals import (
    FinancialPeriod,
    StatementValue,
    analyze_financial_quality,
)
from financial_ai.analysis.peers import PeerCompany, PeerUniverse, compare_company
from financial_ai.analysis.valuation import ValuationInput, analyze_valuation, historical_ranges


def usd_millions(value: float) -> StatementValue:
    return StatementValue(value, "usd_millions")


def test_financial_quality_converts_units_and_displays_decimal_percentages_correctly() -> None:
    periods = [
        FinancialPeriod(
            "2024",
            revenue=usd_millions(100),
            net_income=usd_millions(15),
            equity=usd_millions(50),
            invested_capital=usd_millions(90),
            diluted_shares=StatementValue(100, "shares"),
        ),
        FinancialPeriod(
            "2025",
            revenue=usd_millions(139),
            net_income=usd_millions(20),
            eps=StatementValue(2, "per_share"),
            free_cash_flow=usd_millions(30),
            gross_profit=usd_millions(54.21),
            operating_income=usd_millions(30),
            effective_tax_rate=0.21,
            equity=usd_millions(60),
            invested_capital=usd_millions(100),
            current_assets=usd_millions(80),
            current_liabilities=usd_millions(40),
            total_debt=usd_millions(30),
            diluted_shares=StatementValue(105, "shares"),
            stock_compensation=usd_millions(4),
            capex=usd_millions(-10),
        ),
    ]
    metrics = analyze_financial_quality(periods)
    assert metrics["revenue"].value == 139_000_000
    assert metrics["gross_margin"].value == 0.39
    assert metrics["gross_margin"].display() == "39.0%"
    assert metrics["revenue_growth"].display() == "39.0%"
    assert metrics["current_ratio"].display() == "2.00x"
    assert metrics["roe"].display() == "36.4%"


def test_financial_quality_marks_missing_and_zero_inputs_unavailable() -> None:
    metrics = analyze_financial_quality([FinancialPeriod("2025", revenue=usd_millions(0))])
    assert not metrics["gross_margin"].available
    assert "denominator is zero" in metrics["gross_margin"].display()
    assert not metrics["revenue_growth"].available


def test_valuation_does_not_turn_negative_denominators_into_misleading_ratios() -> None:
    current = analyze_valuation(
        ValuationInput(
            market_cap=1_000,
            enterprise_value=1_100,
            net_income=-20,
            free_cash_flow=-5,
            revenue=200,
            equity=-1,
            ebitda=0,
        )
    )
    assert not current["price_to_earnings"].available
    assert not current["earnings_yield"].available
    assert current["price_to_sales"].display() == "5.00x"
    assert not current["price_to_book"].available
    ranges = historical_ranges(
        [current, analyze_valuation(ValuationInput(market_cap=1_000, revenue=100))]
    )
    assert ranges["price_to_sales"].low == 5
    assert ranges["price_to_sales"].high == 10
    assert ranges["price_to_earnings"].sample_size == 0


def test_peer_universe_manual_overrides_and_percentiles_are_deterministic() -> None:
    universe = PeerUniverse(
        "same industry and US-listed market-cap range", ("MSFT", "GOOG"), ("META",), ("GOOG",)
    )
    assert universe.symbols() == ("MSFT", "META")
    target = PeerCompany(
        "AAPL", "Apple", "Technology", "Hardware", {"revenue_growth": 0.2, "pe": 25}
    )
    peers = [
        PeerCompany(
            "MSFT", "Microsoft", "Technology", "Software", {"revenue_growth": 0.1, "pe": 30}
        ),
        PeerCompany("META", "Meta", "Technology", "Internet", {"revenue_growth": 0.3, "pe": 20}),
    ]
    results = {
        item.metric: item
        for item in compare_company(target, peers, ("revenue_growth", "pe", "missing"))
    }
    assert results["revenue_growth"].percentile == 0.5
    assert results["pe"].peer_count == 2
    assert results["missing"].percentile is None
