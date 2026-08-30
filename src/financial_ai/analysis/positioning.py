"""Options, short-interest, and liquidity context with explicit data quality."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class DataTimeliness(str, Enum):
    CURRENT = "current"
    DELAYED = "delayed"
    INCOMPLETE = "incomplete"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class OptionsStatistics:
    as_of: datetime
    timeliness: DataTimeliness
    implied_volatility: Decimal | None = None
    iv_percentile: Decimal | None = None
    put_call_open_interest_ratio: Decimal | None = None
    unusual_options_volume: bool | None = None
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShortInterest:
    settlement_at: datetime
    published_at: datetime
    timeliness: DataTimeliness
    short_interest_shares: Decimal | None = None
    short_interest_percent_float: Decimal | None = None
    days_to_cover: Decimal | None = None

    def reporting_delay_days(self, as_of: datetime) -> float:
        return max(0.0, (as_of - self.published_at).total_seconds() / 86_400)


@dataclass(frozen=True)
class LiquiditySnapshot:
    as_of: datetime
    timeliness: DataTimeliness
    volume: Decimal | None = None
    average_volume: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    last_price: Decimal | None = None

    @property
    def relative_volume(self) -> Decimal | None:
        if self.volume is None or self.average_volume is None or self.average_volume <= 0:
            return None
        return self.volume / self.average_volume

    @property
    def quoted_spread_bps(self) -> Decimal | None:
        if self.bid is None or self.ask is None or self.last_price is None or self.last_price <= 0:
            return None
        return (self.ask - self.bid) / self.last_price * Decimal(10_000)


@dataclass(frozen=True)
class PositioningContext:
    options: OptionsStatistics | None
    short_interest: ShortInterest | None
    liquidity: LiquiditySnapshot | None
    warnings: tuple[str, ...]


def build_positioning_context(
    options: OptionsStatistics | None,
    short_interest: ShortInterest | None,
    liquidity: LiquiditySnapshot | None,
    *,
    as_of: datetime,
) -> PositioningContext:
    warnings: list[str] = []
    for label, item in (
        ("Options", options),
        ("Short interest", short_interest),
        ("Liquidity", liquidity),
    ):
        if item is None:
            warnings.append(f"{label} data is unavailable.")
        elif item.timeliness is not DataTimeliness.CURRENT:
            warnings.append(f"{label} data is {item.timeliness.value}; do not treat it as current.")
    if short_interest and short_interest.reporting_delay_days(as_of) > 14:
        warnings.append("Short interest reporting delay exceeds 14 days.")
    return PositioningContext(options, short_interest, liquidity, tuple(warnings))
