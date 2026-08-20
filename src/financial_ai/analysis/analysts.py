"""Public analyst-consensus summaries, not proprietary analyst research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


PUBLIC_CONSENSUS_LABEL = "Public analyst consensus; not proprietary analyst reports."


@dataclass(frozen=True)
class RecommendationDistribution:
    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0

    @property
    def total(self) -> int:
        return sum((self.strong_buy, self.buy, self.hold, self.sell, self.strong_sell))


@dataclass(frozen=True)
class PublicAnalystConsensus:
    as_of: datetime
    recommendations: RecommendationDistribution
    mean_target: Decimal | None
    low_target: Decimal | None
    high_target: Decimal | None
    analyst_count: int | None
    revision_direction: str

    @property
    def target_dispersion(self) -> Decimal | None:
        mean_target = self.mean_target
        if (
            self.low_target is None
            or self.high_target is None
            or mean_target is None
            or mean_target == Decimal(0)
        ):
            return None
        return (self.high_target - self.low_target) / mean_target


@dataclass(frozen=True)
class PublicAnalystAction:
    firm: str
    action: str
    published_at: datetime
    target_price: Decimal | None = None
    source_url: str | None = None
