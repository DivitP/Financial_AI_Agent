"""Exchange-calendar-aware earnings scorecards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class ReleaseSession(str, Enum):
    BEFORE_MARKET = "before_market"
    DURING_MARKET = "during_market"
    AFTER_MARKET = "after_market"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExchangeSession:
    """A session supplied by an exchange calendar provider, never assumed from UTC."""

    exchange: str
    opens_at: datetime
    closes_at: datetime

    def classify(self, release_at: datetime | None) -> ReleaseSession:
        if release_at is None:
            return ReleaseSession.UNKNOWN
        if release_at.tzinfo is None or release_at.utcoffset() is None:
            raise ValueError("release_at must include an exchange-calendar timezone")
        if release_at < self.opens_at:
            return ReleaseSession.BEFORE_MARKET
        if release_at >= self.closes_at:
            return ReleaseSession.AFTER_MARKET
        return ReleaseSession.DURING_MARKET


@dataclass(frozen=True)
class EarningsEvent:
    fiscal_period: str
    scheduled_at: datetime
    release_at: datetime | None
    exchange_session: ReleaseSession
    reported_eps: Decimal | None = None
    consensus_eps: Decimal | None = None
    reported_revenue: Decimal | None = None
    consensus_revenue: Decimal | None = None

    def surprise(self, metric: str) -> Decimal | None:
        reported, consensus = {
            "eps": (self.reported_eps, self.consensus_eps),
            "revenue": (self.reported_revenue, self.consensus_revenue),
        }[metric]
        if reported is None or consensus is None or consensus == 0:
            return None
        return (reported - consensus) / abs(consensus)


@dataclass(frozen=True)
class EarningsScorecard:
    historical: tuple[EarningsEvent, ...]
    upcoming: EarningsEvent | None
    eps_revision_direction: str
    revenue_revision_direction: str
    post_earnings_price_reaction: Decimal | None


def revision_direction(previous: Decimal | None, current: Decimal | None) -> str:
    if previous is None or current is None:
        return "unavailable"
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "unchanged"


def price_reaction(
    before_release_close: Decimal | None, after_release_close: Decimal | None
) -> Decimal | None:
    if before_release_close is None or after_release_close is None or before_release_close <= 0:
        return None
    return (after_release_close - before_release_close) / before_release_close
