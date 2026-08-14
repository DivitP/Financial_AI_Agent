from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from financial_ai.domain.models import AssetType
from financial_ai.instruments import CatalogInstrumentResolver, ResolutionOutcome
from financial_ai.instruments.resolver import InstrumentProfile
from financial_ai.providers.contracts import ProviderResult
from financial_ai.providers.errors import ProviderError, ProviderErrorCategory


def _profile(symbol: str, asset_type: AssetType, **kwargs) -> InstrumentProfile:
    return InstrumentProfile(
        symbol=symbol,
        company_name=kwargs.pop("company_name", f"{symbol} Holdings"),
        exchange=kwargs.pop("exchange", "NASDAQ"),
        currency="USD",
        timezone="America/New_York",
        cik=kwargs.pop("cik", "0000320193"),
        asset_type=asset_type,
        **kwargs,
    )


def test_resolver_returns_normalized_stock_and_etf_metadata() -> None:
    resolver = CatalogInstrumentResolver(
        [_profile("AAPL", AssetType.EQUITY), _profile("SPY", AssetType.ETF, cik=None)]
    )

    stock = resolver.resolve("aapl")
    etf = resolver.resolve("SPY")

    assert stock.outcome == ResolutionOutcome.RESOLVED
    assert stock.instrument and stock.instrument.is_stock and stock.instrument.cik == "0000320193"
    assert etf.instrument and etf.instrument.is_etf


@pytest.mark.parametrize(
    ("query", "profiles", "outcome"),
    [
        ("bad symbol!", [], ResolutionOutcome.MALFORMED),
        (
            "ABC",
            [_profile("ABC", AssetType.EQUITY), _profile("ABC", AssetType.ETF)],
            ResolutionOutcome.AMBIGUOUS,
        ),
        ("LEH", [_profile("LEH", AssetType.EQUITY, delisted=True)], ResolutionOutcome.DELISTED),
        ("BTC", [_profile("BTC", AssetType.CRYPTO)], ResolutionOutcome.UNSUPPORTED),
    ],
)
def test_resolver_has_distinct_non_success_outcomes(query, profiles, outcome) -> None:
    assert CatalogInstrumentResolver(profiles).resolve(query).outcome == outcome


def test_provider_result_requires_data_or_a_categorized_error() -> None:
    error = ProviderError(
        provider="fmp",
        category=ProviderErrorCategory.RATE_LIMITED,
        message="Budget exceeded",
        retryable=True,
        retry_after_seconds=60,
    )
    result = ProviderResult[dict[str, str]](provider="fmp", error=error)
    assert result.error and result.error.category == ProviderErrorCategory.RATE_LIMITED

    with pytest.raises(ValidationError, match="exactly one"):
        ProviderResult[dict[str, str]](provider="fmp")
