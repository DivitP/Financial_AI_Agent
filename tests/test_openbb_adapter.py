from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from financial_ai.domain.models import AssetType
from financial_ai.instruments.resolver import InstrumentProfile
from financial_ai.providers.errors import ProviderErrorCategory
from financial_ai.providers.openbb import OpenBBMarketDataAdapter


class FakeOpenBB:
    def __init__(self) -> None:
        self.equity = SimpleNamespace(
            price=SimpleNamespace(quote=self.quote, historical=self.historical),
            profile=self.profile,
        )

    @staticmethod
    def quote(**_):
        return SimpleNamespace(results=[{"last_price": 200.0, "currency": "USD"}])

    @staticmethod
    def profile(**_):
        return SimpleNamespace(
            results=[{"name": "Apple Inc.", "exchange": "NASDAQ", "sector": "Technology"}]
        )

    @staticmethod
    def historical(**_):
        return SimpleNamespace(
            results=[
                {
                    "date": datetime(2026, 8, 14, tzinfo=UTC),
                    "open": 199.0,
                    "high": 201.0,
                    "low": 198.0,
                    "close": 200.0,
                    "volume": 100,
                    "dividend": 0.25,
                    "stock_splits": 0,
                }
            ]
        )


def _instrument() -> InstrumentProfile:
    return InstrumentProfile(
        symbol="AAPL",
        company_name="Apple Inc.",
        exchange="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        cik="0000320193",
        asset_type=AssetType.EQUITY,
    )


def test_openbb_adapter_collects_normalized_market_data_with_metadata() -> None:
    result = asyncio.run(
        OpenBBMarketDataAdapter(client=FakeOpenBB()).collect_market_data(
            _instrument(), uuid4(), "2026-08-01", "2026-08-14"
        )
    )

    assert result.data and result.data.quote.price == 200
    assert len(result.data.ohlcv) == 1
    assert result.data.corporate_actions[0].action_type == "dividend"
    for metadata in [
        result.data.quote.metadata,
        result.data.profile.metadata,
        *(item.metadata for item in result.data.ohlcv),
        *(item.metadata for item in result.data.corporate_actions),
    ]:
        assert metadata.provider == "yfinance"
        assert metadata.retrieved_at.tzinfo is not None
        assert metadata.currency == "USD"
        assert metadata.timezone == "America/New_York"
        assert metadata.adjustment_policy
    assert result.data.calendar.metadata.adjustment_policy


def test_openbb_adapter_reports_missing_extensions_without_importing_openbb() -> None:
    adapter = OpenBBMarketDataAdapter()
    result = asyncio.run(adapter.quote(_instrument(), uuid4()))

    if adapter.capabilities().available:
        pytest.skip("OpenBB optional packages are installed in this environment")
    assert result.error and result.error.category == ProviderErrorCategory.UNSUPPORTED


def test_openbb_provider_selection_is_explicit() -> None:
    with pytest.raises(ValueError, match="provider='yfinance'"):
        OpenBBMarketDataAdapter(provider="fmp")
