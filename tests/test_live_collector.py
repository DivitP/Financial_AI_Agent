import json
from typing import Any
from uuid import uuid4

import pytest

from financial_ai.data.http import SharedHttpClient, HttpResponse
from financial_ai.providers.live import LiveCollector
from financial_ai.analysis.sec_periods import financial_periods
from financial_ai.analysis.fundamentals import analyze_financial_quality
from settings import Settings


def test_chart_collector_uses_one_bounded_request_and_provenance():
    calls = []
    fixture: dict[str, Any] = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "instrumentType": "EQUITY",
                        "currency": "USD",
                        "exchangeTimezoneName": "America/New_York",
                        "exchangeName": "NMS",
                        "regularMarketTime": 1700000000,
                        "regularMarketPrice": 123,
                    },
                    "timestamp": [1700000000 + i * 86400 for i in range(25)],
                    "indicators": {
                        "quote": [{}],
                        "adjclose": [{"adjclose": [100 + i for i in range(25)]}],
                    },
                }
            ]
        }
    }

    def transport(request, *_):
        calls.append(request)
        return HttpResponse(200, {}, json.dumps(fixture).encode())

    collector = LiveCollector(Settings(_env_file=None), http=SharedHttpClient(transport))
    run = {"symbol": "AAPL", "instrument_id": str(uuid4())}
    sources = [collector.collect(lane, run) for lane in ("instrument", "quote", "ohlcv")]
    assert len(calls) == 1
    assert sources[1].payload["price"] == 123
    assert sources[2].payload["adjustment_policy"] == "provider_adjusted_close"
    assert len(sources[2].payload["candles"]) == 25
    assert all(s.payload["currency"] == "USD" and s.published_at.tzinfo for s in sources)
    fixture["chart"]["result"][0]["meta"]["regularMarketPrice"] = float("nan")
    collector.market = fixture["chart"]["result"][0]
    with pytest.raises(ValueError, match="price"):
        collector.collect("quote", run)


def test_sec_mapping_uses_annual_matching_units_not_quarterly_or_mixed_currency():
    def fact(tag, value, start="2025-01-01", unit="USD"):
        return dict(
            tag=tag,
            value=value,
            period_start=start,
            period_end="2025-12-31",
            unit=unit,
            form="10-K",
            filed_at="2026-02-01",
        )

    periods = financial_periods(
        [
            fact("Revenues", 100),
            fact("GrossProfit", 39),
            fact("Revenues", 999, start="2025-10-01"),
            fact("GrossProfit", 999, unit="EUR"),
        ]
    )
    assert len(periods) == 1
    assert analyze_financial_quality(periods)["gross_margin"].display() == "39.0%"


def test_news_cites_original_article_not_feed_discovery():
    xml = b"""<rss><channel><item><title>AAPL announces earnings</title>
    <link>https://publisher.test/releases/earnings</link>
    <pubDate>Mon, 02 Feb 2026 12:00:00 GMT</pubDate></item></channel></rss>"""
    settings = Settings(_env_file=None, research_news_feeds=["https://publisher.test/feed"])
    collector = LiveCollector(
        settings, http=SharedHttpClient(lambda *_: HttpResponse(200, {}, xml))
    )
    source = collector.collect("news", {"symbol": "AAPL"})
    assert str(source.url) == "https://publisher.test/releases/earnings"
    assert source.payload["discovered_from"] == "https://publisher.test/feed"
    assert len(source.payload["articles"]) == 1


def test_live_research_requires_explicit_sec_contact():
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        Settings(_env_file=None, enable_live_research=True, sec_user_agent="")
