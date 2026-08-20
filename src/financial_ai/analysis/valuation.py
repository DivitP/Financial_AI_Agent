"""Valuation ratios that preserve not-meaningful denominators explicitly."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from financial_ai.analysis.fundamentals import MetricResult


@dataclass(frozen=True)
class ValuationInput:
    market_cap: float | None
    enterprise_value: float | None = None
    net_income: float | None = None
    free_cash_flow: float | None = None
    revenue: float | None = None
    equity: float | None = None
    ebitda: float | None = None


@dataclass(frozen=True)
class ValuationRange:
    name: str
    low: float | None
    median: float | None
    high: float | None
    sample_size: int


def _multiple(name: str, numerator: float | None, denominator: float | None) -> MetricResult:
    if numerator is None or denominator is None:
        return MetricResult(name, None, "multiple", "required data is unavailable")
    if denominator <= 0:
        return MetricResult(
            name, None, "multiple", "denominator is zero or negative; ratio is not meaningful"
        )
    return MetricResult(name, numerator / denominator, "multiple")


def _yield(name: str, numerator: float | None, denominator: float | None) -> MetricResult:
    if numerator is None or denominator is None:
        return MetricResult(name, None, "percent", "required data is unavailable")
    if numerator <= 0 or denominator <= 0:
        return MetricResult(
            name,
            None,
            "percent",
            "earnings or cash flow is zero or negative; yield is not meaningful",
        )
    return MetricResult(name, numerator / denominator, "percent")


def analyze_valuation(value: ValuationInput) -> dict[str, MetricResult]:
    return {
        "earnings_yield": _yield("earnings_yield", value.net_income, value.market_cap),
        "free_cash_flow_yield": _yield(
            "free_cash_flow_yield", value.free_cash_flow, value.market_cap
        ),
        "price_to_earnings": _multiple("price_to_earnings", value.market_cap, value.net_income),
        "price_to_sales": _multiple("price_to_sales", value.market_cap, value.revenue),
        "price_to_book": _multiple("price_to_book", value.market_cap, value.equity),
        "ev_to_ebitda": _multiple("ev_to_ebitda", value.enterprise_value, value.ebitda),
    }


def historical_ranges(history: list[dict[str, MetricResult]]) -> dict[str, ValuationRange]:
    """Build transparent ranges from only valid historical observations."""
    names = {name for snapshot in history for name in snapshot}
    return {
        name: _range(
            name,
            [
                snapshot[name].value
                for snapshot in history
                if snapshot.get(name) and snapshot[name].value is not None
            ],
        )
        for name in names
    }


def _range(name: str, values: list[float | None]) -> ValuationRange:
    valid = [value for value in values if value is not None]
    return ValuationRange(
        name,
        min(valid) if valid else None,
        median(valid) if valid else None,
        max(valid) if valid else None,
        len(valid),
    )
