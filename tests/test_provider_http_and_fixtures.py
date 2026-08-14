from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from financial_ai.data.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseTooLargeError,
    SharedHttpClient,
)
from financial_ai.providers.contracts import ProviderResult
from financial_ai.providers.errors import ProviderError, ProviderErrorCategory
from financial_ai.providers.testing import assert_provider_conformance, load_fixture


class FixtureQuote(BaseModel):
    symbol: str
    price: float


def test_identical_requests_are_cached_and_preserve_user_agent() -> None:
    calls = []

    def transport(request, timeout, max_bytes):
        calls.append((request, timeout, max_bytes))
        return HttpResponse(200, {}, b'{"ok":true}')

    client = SharedHttpClient(transport, cache_ttl_seconds=60, sleep=lambda _: None)
    request = HttpRequest(provider="fixture", url="https://example.test/data")

    assert client.fetch(request).status_code == 200
    assert client.fetch(request).status_code == 200
    assert len(calls) == 1
    assert calls[0][0].headers["User-Agent"].startswith("financial-ai-agent/")


def test_429_retries_using_retry_after_instruction() -> None:
    sleeps: list[float] = []
    responses = [
        HttpResponse(429, {"Retry-After": "3"}, b"slow down"),
        HttpResponse(200, {}, b"ok"),
    ]

    def transport(*_):
        return responses.pop(0)

    client = SharedHttpClient(transport, max_retries=2, sleep=sleeps.append)
    assert (
        client.fetch(
            HttpRequest(provider="fixture", url="https://example.test/rate-limit")
        ).status_code
        == 200
    )
    assert sleeps == [3.0]


def test_response_size_limit_is_enforced() -> None:
    client = SharedHttpClient(
        lambda *_: HttpResponse(200, {}, b"12345"), max_response_bytes=4, sleep=lambda _: None
    )
    with pytest.raises(HttpResponseTooLargeError):
        client.fetch(HttpRequest(provider="fixture", url="https://example.test/large"))


def test_fixture_harness_checks_provenance_and_error_contracts() -> None:
    fixture = load_fixture(
        Path(__file__).parent / "fixtures/providers/quote_success.json",
        ProviderResult[FixtureQuote],
    )
    assert_provider_conformance(fixture, "fixture-market")
    assert fixture.data and fixture.data.symbol == "AAPL"

    missing = ProviderResult[FixtureQuote](
        provider="fixture-market",
        error=ProviderError(
            provider="fixture-market",
            category=ProviderErrorCategory.NOT_FOUND,
            message="No quote",
        ),
    )
    assert_provider_conformance(missing, "fixture-market")
