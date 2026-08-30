"""Exposure-driven macro and industry context selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from financial_ai.providers.contracts import MacroObservation


class Exposure(str, Enum):
    RATES = "rates"
    INFLATION = "inflation"
    LABOR = "labor"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    INDUSTRY = "industry"


@dataclass(frozen=True)
class CompanyExposure:
    industry: str
    exposures: frozenset[Exposure]
    commodity_series: tuple[str, ...] = ()
    currency_series: tuple[str, ...] = ()
    industry_series: tuple[str, ...] = ()


@dataclass(frozen=True)
class MacroSeries:
    series_id: str
    exposure: Exposure
    rationale: str


@dataclass(frozen=True)
class MacroContext:
    selected_series: tuple[MacroSeries, ...]
    observations: tuple[MacroObservation, ...]


BASE_SERIES = {
    Exposure.RATES: MacroSeries(
        "FEDFUNDS", Exposure.RATES, "Interest-rate-sensitive financing and valuation exposure."
    ),
    Exposure.INFLATION: MacroSeries(
        "CPIAUCSL", Exposure.INFLATION, "Input-cost and consumer purchasing-power exposure."
    ),
    Exposure.LABOR: MacroSeries(
        "PAYEMS", Exposure.LABOR, "Labor demand and wage-pressure exposure."
    ),
}


def select_macro_series(exposure: CompanyExposure) -> tuple[MacroSeries, ...]:
    """Select only series justified by a documented company exposure."""
    selected = [
        BASE_SERIES[item]
        for item in (Exposure.RATES, Exposure.INFLATION, Exposure.LABOR)
        if item in exposure.exposures
    ]
    if Exposure.COMMODITY in exposure.exposures:
        selected.extend(
            MacroSeries(series, Exposure.COMMODITY, f"Commodity exposure for {exposure.industry}.")
            for series in exposure.commodity_series
        )
    if Exposure.CURRENCY in exposure.exposures:
        selected.extend(
            MacroSeries(series, Exposure.CURRENCY, "Foreign-currency revenue or cost exposure.")
            for series in exposure.currency_series
        )
    if Exposure.INDUSTRY in exposure.exposures:
        selected.extend(
            MacroSeries(
                series, Exposure.INDUSTRY, f"Industry demand indicator for {exposure.industry}."
            )
            for series in exposure.industry_series
        )
    return tuple(selected)


def build_macro_context(
    exposure: CompanyExposure, observations: list[MacroObservation]
) -> MacroContext:
    selected = select_macro_series(exposure)
    allowed = {series.series_id for series in selected}
    return MacroContext(selected, tuple(item for item in observations if item.series_id in allowed))
