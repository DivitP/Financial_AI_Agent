"""ETF-specific research that never substitutes corporate fundamentals."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from financial_ai.domain.models import AssetType


@dataclass(frozen=True)
class ETFHolding:
    symbol: str
    name: str
    weight: Decimal
    sector: str | None = None


@dataclass(frozen=True)
class ETFProfile:
    expense_ratio: Decimal | None
    holdings: tuple[ETFHolding, ...]
    average_volume: Decimal | None = None
    tracking_difference: Decimal | None = None


@dataclass(frozen=True)
class ETFAnalysis:
    top_ten_weight: Decimal
    concentration_hhi: Decimal
    sector_exposure: dict[str, Decimal]
    expense_ratio: Decimal | None
    average_volume: Decimal | None
    tracking_difference: Decimal | None
    constituent_risks: tuple[str, ...]


CORPORATE_SECTIONS = ("earnings", "statements", "filings", "guidance", "analysts")
ETF_SECTIONS = (
    "holdings",
    "concentration",
    "sectors",
    "fees",
    "liquidity",
    "tracking",
    "constituent_risk",
)


def research_sections(asset_type: AssetType) -> tuple[str, ...]:
    return ETF_SECTIONS if asset_type is AssetType.ETF else CORPORATE_SECTIONS


def analyze_etf(profile: ETFProfile) -> ETFAnalysis:
    holdings = sorted(profile.holdings, key=lambda item: item.weight, reverse=True)
    sectors: dict[str, Decimal] = {}
    risks: list[str] = []
    for holding in holdings:
        if holding.sector:
            sectors[holding.sector] = sectors.get(holding.sector, Decimal(0)) + holding.weight
        if holding.weight >= Decimal("0.10"):
            risks.append(f"{holding.symbol} represents {holding.weight * 100:.1f}% of the fund.")
    return ETFAnalysis(
        top_ten_weight=sum((item.weight for item in holdings[:10]), Decimal(0)),
        concentration_hhi=sum((item.weight * item.weight for item in holdings), Decimal(0)),
        sector_exposure=sectors,
        expense_ratio=profile.expense_ratio,
        average_volume=profile.average_volume,
        tracking_difference=profile.tracking_difference,
        constituent_risks=tuple(risks),
    )
