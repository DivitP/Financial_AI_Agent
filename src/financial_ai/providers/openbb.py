"""Optional OpenBB market-data adapter with an explicit yfinance provider selection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from financial_ai.instruments.resolver import InstrumentProfile
from financial_ai.providers.contracts import ProviderResult, Provenance
from financial_ai.providers.errors import ProviderError, ProviderErrorCategory


REQUIRED_OPENBB_PACKAGES = ("openbb-core", "openbb-equity", "openbb-yfinance")


class MarketObservationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str
    retrieved_at: datetime
    currency: str = Field(min_length=3, max_length=3)
    timezone: str = Field(min_length=1)
    adjustment_policy: str = Field(min_length=1)

    @model_validator(mode="after")
    def has_timezone(self) -> "MarketObservationMetadata":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone offset")
        return self


class QuoteObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instrument_id: UUID
    price: Decimal
    as_of: datetime
    metadata: MarketObservationMetadata


class CompanyProfileObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instrument_id: UUID
    company_name: str
    exchange: str | None = None
    sector: str | None = None
    metadata: MarketObservationMetadata


class OHLCVObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instrument_id: UUID
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(ge=0)
    metadata: MarketObservationMetadata


class CorporateActionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instrument_id: UUID
    action_type: str
    effective_at: datetime
    value: Decimal | None = None
    metadata: MarketObservationMetadata


class MarketCalendarObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    exchange: str
    session_date: str
    is_open: bool | None = None
    timezone: str
    metadata: MarketObservationMetadata


class OpenBBCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selected_provider: str
    installed: dict[str, str] = Field(default_factory=dict)
    missing_extensions: list[str] = Field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.missing_extensions


class MarketDataCollection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    quote: QuoteObservation
    profile: CompanyProfileObservation
    ohlcv: list[OHLCVObservation]
    corporate_actions: list[CorporateActionObservation]
    calendar: MarketCalendarObservation


class OpenBBMarketDataAdapter:
    """Normalizes only selected OpenBB/yfinance responses; no implicit provider fallback."""

    def __init__(self, *, provider: str = "yfinance", client: Any | None = None) -> None:
        if provider != "yfinance":
            raise ValueError("OpenBB adapter currently supports only explicit provider='yfinance'")
        self.provider = provider
        self._client = client

    def capabilities(self) -> OpenBBCapabilities:
        installed: dict[str, str] = {}
        missing: list[str] = []
        for package in REQUIRED_OPENBB_PACKAGES:
            try:
                installed[package] = version(package)
            except PackageNotFoundError:
                missing.append(package)
        return OpenBBCapabilities(
            selected_provider=self.provider, installed=installed, missing_extensions=missing
        )

    def client(self) -> Any:
        if self._client is not None:
            return self._client
        capabilities = self.capabilities()
        if not capabilities.available:
            raise RuntimeError(
                f"Missing OpenBB extensions: {', '.join(capabilities.missing_extensions)}"
            )
        from openbb import obb

        return obb

    async def quote(
        self, instrument: InstrumentProfile, instrument_id: UUID
    ) -> ProviderResult[QuoteObservation]:
        return self._collect_one(instrument, instrument_id, "quote")

    async def profile(
        self, instrument: InstrumentProfile, instrument_id: UUID
    ) -> ProviderResult[CompanyProfileObservation]:
        return self._collect_one(instrument, instrument_id, "profile")

    async def collect_market_data(
        self, instrument: InstrumentProfile, instrument_id: UUID, start_date: str, end_date: str
    ) -> ProviderResult[MarketDataCollection]:
        """Collect yfinance quote/profile/history; actions are carried by historical data."""

        capabilities = self.capabilities()
        if self._client is None and not capabilities.available:
            return ProviderResult(
                provider="openbb",
                error=ProviderError(
                    provider="openbb",
                    category=ProviderErrorCategory.UNSUPPORTED,
                    message=f"Missing OpenBB extensions: {', '.join(capabilities.missing_extensions)}",
                ),
            )
        try:
            client = self.client()
            quote_item = _first_result(
                client.equity.price.quote(symbol=instrument.symbol, provider=self.provider)
            )
            profile_item = _first_result(
                client.equity.profile(symbol=instrument.symbol, provider=self.provider)
            )
            historical = _all_results(
                client.equity.price.historical(
                    symbol=instrument.symbol,
                    start_date=start_date,
                    end_date=end_date,
                    provider=self.provider,
                    include_actions=True,
                    adjustment="splits_only",
                )
            )
            metadata = _metadata(quote_item, self.provider, instrument)
            quote = QuoteObservation(
                instrument_id=instrument_id,
                price=Decimal(str(_value(quote_item, "last_price", "price"))),
                as_of=metadata.retrieved_at,
                metadata=metadata,
            )
            profile = CompanyProfileObservation(
                instrument_id=instrument_id,
                company_name=str(_value(profile_item, "name", "legal_name")),
                exchange=_value_or_none(profile_item, "exchange", "stock_exchange"),
                sector=_value_or_none(profile_item, "sector"),
                metadata=metadata,
            )
            ohlcv = [
                OHLCVObservation(
                    instrument_id=instrument_id,
                    timestamp=_timestamp(row, "date", "timestamp"),
                    open=Decimal(str(_value(row, "open"))),
                    high=Decimal(str(_value(row, "high"))),
                    low=Decimal(str(_value(row, "low"))),
                    close=Decimal(str(_value(row, "close"))),
                    volume=int(row.get("volume") or 0),
                    metadata=metadata,
                )
                for row in historical
            ]
            actions = _actions(historical, instrument_id, metadata)
            calendar = MarketCalendarObservation(
                exchange=instrument.exchange,
                session_date=end_date,
                timezone=instrument.timezone,
                metadata=metadata,
            )
            return ProviderResult(
                provider="openbb",
                data=MarketDataCollection(
                    quote=quote,
                    profile=profile,
                    ohlcv=ohlcv,
                    corporate_actions=actions,
                    calendar=calendar,
                ),
                as_of=metadata.retrieved_at,
                provenance=[_provenance(quote_item, metadata)],
            )
        except Exception:
            return ProviderResult(
                provider="openbb",
                error=ProviderError(
                    provider="openbb",
                    category=ProviderErrorCategory.UNAVAILABLE,
                    message="OpenBB request failed",
                    retryable=True,
                ),
            )

    def _collect_one(self, instrument: InstrumentProfile, instrument_id: UUID, kind: str):
        capabilities = self.capabilities()
        if self._client is None and not capabilities.available:
            return ProviderResult(
                provider="openbb",
                error=ProviderError(
                    provider="openbb",
                    category=ProviderErrorCategory.UNSUPPORTED,
                    message=f"Missing OpenBB extensions: {', '.join(capabilities.missing_extensions)}",
                ),
            )
        try:
            response = (
                self.client().equity.price.quote(symbol=instrument.symbol, provider=self.provider)
                if kind == "quote"
                else self.client().equity.profile(symbol=instrument.symbol, provider=self.provider)
            )
            item = _first_result(response)
            metadata = _metadata(item, self.provider, instrument)
            data = (
                QuoteObservation(
                    instrument_id=instrument_id,
                    price=Decimal(str(_value(item, "last_price", "price"))),
                    as_of=metadata.retrieved_at,
                    metadata=metadata,
                )
                if kind == "quote"
                else CompanyProfileObservation(
                    instrument_id=instrument_id,
                    company_name=str(_value(item, "name", "legal_name")),
                    exchange=_value(item, "exchange", "stock_exchange"),
                    sector=_value(item, "sector"),
                    metadata=metadata,
                )
            )
            return ProviderResult(
                provider="openbb",
                data=data,
                as_of=metadata.retrieved_at,
                provenance=[_provenance(item, metadata)],
            )
        except Exception:
            return ProviderResult(
                provider="openbb",
                error=ProviderError(
                    provider="openbb",
                    category=ProviderErrorCategory.UNAVAILABLE,
                    message="OpenBB request failed",
                    retryable=True,
                ),
            )


def _first_result(response: Any) -> Mapping[str, Any]:
    results = _all_results(response)
    if not results:
        raise ValueError("OpenBB returned no results")
    item = results[0]
    return item if isinstance(item, Mapping) else vars(item)


def _all_results(response: Any) -> list[Mapping[str, Any]]:
    results = getattr(
        response, "results", response.get("results") if isinstance(response, dict) else None
    )
    if not results:
        raise ValueError("OpenBB returned no results")
    return [item if isinstance(item, Mapping) else vars(item) for item in results]


def _value(item: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if item.get(name) is not None:
            return item[name]
    raise ValueError(f"OpenBB response missing required field: {names[0]}")


def _value_or_none(item: Mapping[str, Any], *names: str) -> Any | None:
    for name in names:
        if item.get(name) is not None:
            return item[name]
    return None


def _timestamp(item: Mapping[str, Any], *names: str) -> datetime:
    value = _value(item, *names)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.astimezone()
    return datetime.fromisoformat(str(value)).astimezone()


def _actions(
    rows: list[Mapping[str, Any]], instrument_id: UUID, metadata: MarketObservationMetadata
) -> list[CorporateActionObservation]:
    actions: list[CorporateActionObservation] = []
    for row in rows:
        timestamp = _timestamp(row, "date", "timestamp")
        for name, action_type in (("dividend", "dividend"), ("stock_splits", "stock_split")):
            value = row.get(name)
            if value not in (None, 0, 0.0):
                actions.append(
                    CorporateActionObservation(
                        instrument_id=instrument_id,
                        action_type=action_type,
                        effective_at=timestamp,
                        value=Decimal(str(value)),
                        metadata=metadata,
                    )
                )
    return actions


def _metadata(
    item: Mapping[str, Any], provider: str, instrument: InstrumentProfile
) -> MarketObservationMetadata:
    retrieved_at = datetime.now().astimezone()
    return MarketObservationMetadata(
        provider=provider,
        retrieved_at=retrieved_at,
        currency=str(item.get("currency") or instrument.currency).upper(),
        timezone=instrument.timezone,
        adjustment_policy="provider_adjusted_when_available",
    )


def _provenance(item: Mapping[str, Any], metadata: MarketObservationMetadata) -> Provenance:
    return Provenance(
        provider="openbb",
        source_url=str(item.get("url") or "https://docs.openbb.co/"),
        retrieved_at=metadata.retrieved_at,
        terms_classification="provider-terms-required",
    )
