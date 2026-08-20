"""Deterministic, unit-aware financial quality calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AmountUnit = Literal["usd", "usd_thousands", "usd_millions", "shares", "per_share"]


@dataclass(frozen=True)
class StatementValue:
    value: float
    unit: AmountUnit

    def usd(self) -> float | None:
        return {
            "usd": self.value,
            "usd_thousands": self.value * 1_000,
            "usd_millions": self.value * 1_000_000,
        }.get(self.unit)


@dataclass(frozen=True)
class FinancialPeriod:
    label: str
    revenue: StatementValue | None = None
    net_income: StatementValue | None = None
    eps: StatementValue | None = None
    free_cash_flow: StatementValue | None = None
    gross_profit: StatementValue | None = None
    operating_income: StatementValue | None = None
    effective_tax_rate: float | None = None
    equity: StatementValue | None = None
    invested_capital: StatementValue | None = None
    current_assets: StatementValue | None = None
    current_liabilities: StatementValue | None = None
    total_debt: StatementValue | None = None
    diluted_shares: StatementValue | None = None
    stock_compensation: StatementValue | None = None
    capex: StatementValue | None = None


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: float | None
    unit: Literal["percent", "multiple", "currency", "per_share"]
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.value is not None

    def display(self) -> str:
        if self.value is None:
            return f"Unavailable: {self.unavailable_reason or 'missing data'}"
        if self.unit == "percent":
            return f"{self.value * 100:.1f}%"
        if self.unit == "multiple":
            return f"{self.value:.2f}x"
        if self.unit == "currency":
            return f"${self.value:,.0f}"
        return f"${self.value:.2f}"


def _amount(value: StatementValue | None) -> float | None:
    return value.usd() if value else None


def _ratio(
    name: str,
    numerator: float | None,
    denominator: float | None,
    *,
    unit: Literal["percent", "multiple"] = "percent",
) -> MetricResult:
    if denominator is None:
        return MetricResult(name, None, unit, "denominator is unavailable")
    if denominator == 0:
        return MetricResult(name, None, unit, "denominator is zero")
    if numerator is None:
        return MetricResult(name, None, unit, "numerator is unavailable")
    return MetricResult(name, numerator / denominator, unit)


def _growth(name: str, current: float | None, previous: float | None) -> MetricResult:
    if current is None or previous is None:
        return MetricResult(name, None, "percent", "current or prior period is unavailable")
    if previous == 0:
        return MetricResult(name, None, "percent", "prior period is zero")
    return MetricResult(name, (current - previous) / abs(previous), "percent")


def analyze_financial_quality(periods: list[FinancialPeriod]) -> dict[str, MetricResult]:
    """Return latest-period quality metrics; ratios are decimals until display time."""
    if not periods:
        return {"data": MetricResult("data", None, "percent", "no financial periods supplied")}
    current, previous = periods[-1], periods[-2] if len(periods) > 1 else None
    revenue, prior_revenue = (
        _amount(current.revenue),
        _amount(previous.revenue) if previous else None,
    )
    fcf, prior_fcf = (
        _amount(current.free_cash_flow),
        _amount(previous.free_cash_flow) if previous else None,
    )
    capex = _amount(current.capex)
    eps = current.eps.value if current.eps and current.eps.unit == "per_share" else None
    prior_eps = (
        previous.eps.value
        if previous and previous.eps and previous.eps.unit == "per_share"
        else None
    )
    average_equity = _average(
        _amount(current.equity), _amount(previous.equity) if previous else None
    )
    average_capital = _average(
        _amount(current.invested_capital), _amount(previous.invested_capital) if previous else None
    )
    operating_income = _amount(current.operating_income)
    nopat = (
        operating_income * (1 - current.effective_tax_rate)
        if operating_income is not None and current.effective_tax_rate is not None
        else None
    )
    return {
        "revenue": MetricResult(
            "revenue",
            revenue,
            "currency",
            None if revenue is not None else "revenue is unavailable",
        ),
        "eps": MetricResult(
            "eps",
            eps,
            "per_share",
            None if eps is not None else "EPS per-share data is unavailable",
        ),
        "free_cash_flow": MetricResult(
            "free_cash_flow",
            fcf,
            "currency",
            None if fcf is not None else "free cash flow is unavailable",
        ),
        "gross_margin": _ratio("gross_margin", _amount(current.gross_profit), revenue),
        "operating_margin": _ratio("operating_margin", operating_income, revenue),
        "roe": _ratio("roe", _amount(current.net_income), average_equity),
        "roic": _ratio("roic", nopat, average_capital),
        "current_ratio": _ratio(
            "current_ratio",
            _amount(current.current_assets),
            _amount(current.current_liabilities),
            unit="multiple",
        ),
        "debt_to_equity": _ratio(
            "debt_to_equity", _amount(current.total_debt), _amount(current.equity), unit="multiple"
        ),
        "dilution_growth": _growth(
            "dilution_growth",
            _shares(current.diluted_shares),
            _shares(previous.diluted_shares) if previous else None,
        ),
        "stock_compensation_to_revenue": _ratio(
            "stock_compensation_to_revenue", _amount(current.stock_compensation), revenue
        ),
        "capex_to_revenue": _ratio(
            "capex_to_revenue", abs(capex) if capex is not None else None, revenue
        ),
        "revenue_growth": _growth("revenue_growth", revenue, prior_revenue),
        "eps_growth": _growth("eps_growth", eps, prior_eps),
        "free_cash_flow_growth": _growth("free_cash_flow_growth", fcf, prior_fcf),
    }


def _shares(value: StatementValue | None) -> float | None:
    return value.value if value and value.unit == "shares" else None


def _average(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return (current + previous) / 2
