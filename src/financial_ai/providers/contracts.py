"""Typed ports and normalized responses for financial data providers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Generic, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from financial_ai.domain.models import AssetType
from financial_ai.instruments.resolver import InstrumentProfile, ResolutionResult
from financial_ai.providers.errors import ProviderError


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


T = TypeVar("T")


class Provenance(ProviderModel):
    provider: str
    source_url: str
    retrieved_at: datetime
    terms_classification: str

    @model_validator(mode="after")
    def has_timezone(self) -> "Provenance":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone offset")
        return self


class ProviderResult(ProviderModel, Generic[T]):
    provider: str
    data: T | None = None
    error: ProviderError | None = None
    as_of: datetime | None = None
    provenance: list[Provenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_exactly_one_outcome(self) -> "ProviderResult[T]":
        if (self.data is None) == (self.error is None):
            raise ValueError("provider result requires exactly one of data or error")
        if self.data is not None and not self.provenance:
            raise ValueError("successful provider result requires provenance")
        if self.as_of is not None and (self.as_of.tzinfo is None or self.as_of.utcoffset() is None):
            raise ValueError("as_of must include a timezone offset")
        return self


class PriceBar(ProviderModel):
    instrument_id: UUID
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    adjusted: bool


class Quote(ProviderModel):
    instrument_id: UUID
    price: Decimal
    currency: str = Field(min_length=3, max_length=3)
    as_of: datetime


class FinancialStatement(ProviderModel):
    instrument_id: UUID
    statement_type: str
    period_end: datetime
    filing_date: datetime | None = None
    currency: str = Field(min_length=3, max_length=3)
    values: dict[str, Decimal]


class Filing(ProviderModel):
    accession_number: str
    instrument_id: UUID
    form_type: str
    filing_date: datetime
    url: str
    title: str


class Estimate(ProviderModel):
    instrument_id: UUID
    metric: str
    period_end: datetime
    value: Decimal
    currency: str | None = None
    analyst_count: int | None = Field(default=None, ge=0)


class EarningsRelease(ProviderModel):
    instrument_id: UUID
    fiscal_period: str
    scheduled_at: datetime
    release_at: datetime | None = None
    exchange: str
    release_session: str
    reported_eps: Decimal | None = None
    consensus_eps: Decimal | None = None
    reported_revenue: Decimal | None = None
    consensus_revenue: Decimal | None = None


class PublicConsensus(ProviderModel):
    instrument_id: UUID
    as_of: datetime
    recommendation_counts: dict[str, int]
    mean_target: Decimal | None = None
    low_target: Decimal | None = None
    high_target: Decimal | None = None
    analyst_count: int | None = Field(default=None, ge=0)
    revision_direction: str


class PublicAnalystAction(ProviderModel):
    instrument_id: UUID
    firm: str
    action: str
    published_at: datetime
    source_url: str
    target_price: Decimal | None = None


class NewsItem(ProviderModel):
    url: str
    headline: str
    publisher: str
    published_at: datetime
    summary: str | None = None


class MacroObservation(ProviderModel):
    series_id: str
    observed_at: datetime
    value: Decimal
    unit: str


class OwnershipRecord(ProviderModel):
    instrument_id: UUID
    holder_name: str
    shares: Decimal
    reported_at: datetime
    source_filing: str | None = None


class InsiderTransaction(ProviderModel):
    instrument_id: UUID
    reporter: str
    form_type: str
    transaction_code: str
    acquired_disposed: str
    transaction_at: datetime | None = None
    filed_at: datetime
    shares: Decimal | None = None
    planned: bool = False


class OwnershipChange(ProviderModel):
    instrument_id: UUID
    reporter: str
    form_type: str
    filed_at: datetime
    shares: Decimal | None = None
    ownership_before: Decimal | None = None
    ownership_after: Decimal | None = None


class ForecastOutput(ProviderModel):
    instrument_id: UUID
    model_name: str
    horizon: str
    generated_at: datetime
    direction: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class InstrumentDirectoryProvider(Protocol):
    async def resolve_instrument(self, query: str) -> ProviderResult[ResolutionResult]: ...


class MarketDataProvider(Protocol):
    async def quote(self, instrument: InstrumentProfile) -> ProviderResult[Quote]: ...

    async def price_bars(
        self, instrument: InstrumentProfile, start: datetime, end: datetime
    ) -> ProviderResult[list[PriceBar]]: ...


class StatementsProvider(Protocol):
    async def statements(
        self, instrument: InstrumentProfile
    ) -> ProviderResult[list[FinancialStatement]]: ...


class FilingsProvider(Protocol):
    async def filings(self, instrument: InstrumentProfile) -> ProviderResult[list[Filing]]: ...


class EstimatesProvider(Protocol):
    async def estimates(self, instrument: InstrumentProfile) -> ProviderResult[list[Estimate]]: ...


class EarningsProvider(Protocol):
    async def earnings(
        self, instrument: InstrumentProfile
    ) -> ProviderResult[list[EarningsRelease]]: ...


class PublicAnalystProvider(Protocol):
    async def public_consensus(
        self, instrument: InstrumentProfile
    ) -> ProviderResult[PublicConsensus]: ...

    async def public_actions(
        self, instrument: InstrumentProfile
    ) -> ProviderResult[list[PublicAnalystAction]]: ...


class NewsProvider(Protocol):
    async def news(self, instrument: InstrumentProfile) -> ProviderResult[list[NewsItem]]: ...


class MacroProvider(Protocol):
    async def observations(self, series_id: str) -> ProviderResult[list[MacroObservation]]: ...


class OwnershipProvider(Protocol):
    async def ownership(
        self, instrument: InstrumentProfile
    ) -> ProviderResult[list[OwnershipRecord]]: ...

    async def insider_transactions(
        self, instrument: InstrumentProfile
    ) -> ProviderResult[list[InsiderTransaction]]: ...

    async def ownership_changes(
        self, instrument: InstrumentProfile
    ) -> ProviderResult[list[OwnershipChange]]: ...


class ForecastsProvider(Protocol):
    async def forecast(self, instrument: InstrumentProfile) -> ProviderResult[ForecastOutput]: ...
