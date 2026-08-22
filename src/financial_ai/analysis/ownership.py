"""Transparent SEC insider and ownership activity classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class OwnershipEventType(str, Enum):
    PURCHASE = "purchase"
    PLANNED_SALE = "planned_sale"
    SALE = "sale"
    GRANT = "grant"
    DISPOSITION = "disposition"
    BENEFICIAL_OWNERSHIP_CHANGE = "beneficial_ownership_change"
    INSTITUTIONAL_HOLDING_CHANGE = "institutional_holding_change"
    OTHER = "other"


@dataclass(frozen=True)
class OwnershipActivity:
    form_type: str
    reporter: str
    event_type: OwnershipEventType
    transaction_at: datetime | None
    filed_at: datetime
    shares: Decimal | None
    ownership_before: Decimal | None = None
    ownership_after: Decimal | None = None
    planned: bool = False

    @property
    def reporting_delay_days(self) -> float | None:
        if self.transaction_at is None:
            return None
        return max(0.0, (self.filed_at - self.transaction_at).total_seconds() / 86_400)


def classify_form4(
    transaction_code: str, acquired_disposed: str, *, planned: bool = False
) -> OwnershipEventType:
    code, direction = transaction_code.upper(), acquired_disposed.upper()
    if code in {"A", "M"} and direction == "A":
        return OwnershipEventType.GRANT
    if code == "P" and direction == "A":
        return OwnershipEventType.PURCHASE
    if code == "S" and direction == "D":
        return OwnershipEventType.PLANNED_SALE if planned else OwnershipEventType.SALE
    if direction == "D":
        return OwnershipEventType.DISPOSITION
    return OwnershipEventType.OTHER


def classify_ownership_form(form_type: str) -> OwnershipEventType:
    normalized = form_type.upper().replace("/A", "")
    if normalized in {"SC 13D", "SC 13G"}:
        return OwnershipEventType.BENEFICIAL_OWNERSHIP_CHANGE
    if normalized == "13F-HR":
        return OwnershipEventType.INSTITUTIONAL_HOLDING_CHANGE
    return OwnershipEventType.OTHER
