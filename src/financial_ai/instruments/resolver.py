"""Provider-neutral symbol resolution with explicit non-success outcomes."""

from __future__ import annotations

import re
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from financial_ai.domain.models import AssetType


class ResolutionOutcome(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    DELISTED = "delisted"
    UNSUPPORTED = "unsupported"
    MALFORMED = "malformed"
    NOT_FOUND = "not_found"


class InstrumentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str = Field(min_length=1, max_length=15)
    company_name: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    timezone: str = Field(min_length=1)
    cik: str | None = Field(default=None, pattern=r"^\d{10}$")
    asset_type: AssetType
    delisted: bool = False

    @property
    def is_stock(self) -> bool:
        return self.asset_type == AssetType.EQUITY

    @property
    def is_etf(self) -> bool:
        return self.asset_type == AssetType.ETF


class ResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    outcome: ResolutionOutcome
    query: str
    instrument: InstrumentProfile | None = None
    candidates: list[InstrumentProfile] = Field(default_factory=list)
    message: str


class CatalogInstrumentResolver:
    """A test/local resolver; replace its catalog with a provider-backed directory adapter."""

    def __init__(self, instruments: Iterable[InstrumentProfile]) -> None:
        self.instruments = tuple(instruments)

    def resolve(self, query: str) -> ResolutionResult:
        normalized = query.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,14}", normalized):
            return ResolutionResult(
                outcome=ResolutionOutcome.MALFORMED,
                query=query,
                message="Symbol contains unsupported characters or exceeds the maximum length.",
            )
        candidates = [item for item in self.instruments if item.symbol.upper() == normalized]
        if not candidates:
            return ResolutionResult(
                outcome=ResolutionOutcome.NOT_FOUND,
                query=query,
                message="No supported instrument matched this symbol.",
            )
        supported = [
            item for item in candidates if item.asset_type in {AssetType.EQUITY, AssetType.ETF}
        ]
        if not supported:
            return ResolutionResult(
                outcome=ResolutionOutcome.UNSUPPORTED,
                query=query,
                candidates=candidates,
                message="The symbol is known but its asset type is not currently supported.",
            )
        active = [item for item in supported if not item.delisted]
        if not active:
            return ResolutionResult(
                outcome=ResolutionOutcome.DELISTED,
                query=query,
                candidates=supported,
                message="The symbol is known but all matching instruments are delisted.",
            )
        if len(active) > 1:
            return ResolutionResult(
                outcome=ResolutionOutcome.AMBIGUOUS,
                query=query,
                candidates=active,
                message="More than one active stock or ETF matches this symbol.",
            )
        return ResolutionResult(
            outcome=ResolutionOutcome.RESOLVED,
            query=query,
            instrument=active[0],
            message="Instrument resolved.",
        )
