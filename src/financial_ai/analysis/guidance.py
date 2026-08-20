"""Cited management guidance records; model inferences remain separate."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID


class GuidanceOrigin(str, Enum):
    EXPLICIT_MANAGEMENT = "explicit_management"
    INFERRED = "inferred"


@dataclass(frozen=True)
class GuidanceStatement:
    metric: str
    period: str
    low: Decimal | None
    high: Decimal | None
    unit: str
    origin: GuidanceOrigin
    evidence_id: UUID
    exact_wording: str | None = None

    def __post_init__(self) -> None:
        if self.origin is GuidanceOrigin.EXPLICIT_MANAGEMENT and not self.exact_wording:
            raise ValueError("explicit management guidance requires cited wording")
        if self.origin is GuidanceOrigin.INFERRED and self.exact_wording:
            raise ValueError("inferred guidance must not be presented as management wording")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("guidance low cannot exceed guidance high")


@dataclass(frozen=True)
class GuidanceComparison:
    current: GuidanceStatement
    previous: GuidanceStatement | None
    actual: Decimal | None
    change_direction: str
    result_position: str | None


def compare_guidance(
    current: GuidanceStatement, previous: GuidanceStatement | None, actual: Decimal | None
) -> GuidanceComparison:
    direction = "unavailable"
    if previous and current.low is not None and previous.low is not None:
        direction = (
            "raised"
            if current.low > previous.low
            else "lowered"
            if current.low < previous.low
            else "unchanged"
        )
    position = None
    if actual is not None and current.low is not None and current.high is not None:
        position = (
            "above" if actual > current.high else "below" if actual < current.low else "within"
        )
    return GuidanceComparison(current, previous, actual, direction, position)
