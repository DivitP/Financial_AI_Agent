"""Offline provider fallback, provenance, and report regressions for Flask."""

import json
from datetime import UTC, datetime, timedelta
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup

from financial_ai.analysis.legacy_technical import build_technical_report
from financial_ai.data.http import HttpResponse, SharedHttpClient
from financial_ai.providers.legacy_live import LegacyLiveProvider, history_frame, symbol
from financial_ai.reporting_legacy import build_live_research, timestamp
from financial_ai.security import sanitized_markdown
from settings import Settings

NOW = datetime(2026, 11, 11, tzinfo=UTC)


def rows():
    return [
        dict(
            symbol="NVDA",
            date=(NOW - timedelta(days=30 - i)).date().isoformat(),
            open=100 + i,
            high=102 + i,
            low=99 + i,
            close=101 + i,
            volume=1000 + i,
        )
        for i in range(25)
    ]


def yahoo():
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "NVDA",
                        "currency": "USD",
                        "regularMarketPrice": 125,
                        "regularMarketTime": int(NOW.timestamp()),
                    },
                    "timestamp": [
                        int((NOW - timedelta(days=30 - i)).timestamp()) for i in range(25)
                    ],
                    "indicators": {
                        "quote": [
                            {
                                key: [row[key] for row in rows()]
                                for key in ("open", "high", "low", "close", "volume")
                            }
                        ]
                    },
                }
            ]
        }
    }


class FixtureHttp:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = []

    def fetch(self, request):
        url = urlsplit(request.url)
        self.calls.append(request.url)
        path = url.path.removeprefix("/stable/")
        if path in self.overrides:
            value = self.overrides[path]
            if isinstance(value, Exception):
                raise value
            if isinstance(value, int):
                return HttpResponse(value, {}, b"private error body")
            return HttpResponse(
                200, {}, value if isinstance(value, bytes) else json.dumps(value).encode()
            )
        if url.hostname == "query1.finance.yahoo.com":
            payload = yahoo()
        elif url.hostname == "finance.yahoo.com":
            return HttpResponse(
                200,
                {},
                b"<rss><channel><item><title>NVDA news</title>"
                b"<link>https://publisher.test/nvda</link>"
                b"<pubDate>Wed, 11 Nov 2026 00:00:00 GMT</pubDate>"
                b"</item></channel></rss>",
            )
        elif path == "news/stock":
            return HttpResponse(402, {}, b"subscription restricted")
        elif path == "historical-price-eod/full":
            payload = rows()
        else:
            payload = [
                {
                    "symbol": "NVDA",
                    "price": 125,
                    "timestamp": int(NOW.timestamp()),
                    "companyName": "Fixture company",
                    "currency": "USD",
                    "sector": "Technology",
                    "revenue": 1000,
                    "grossProfit": 390,
                    "netIncome": 200,
                    "reportedCurrency": "USD",
                    "date": "2026-01-31",
                    "period": "FY",
                    "fiscalYear": "2026",
                    "filingDate": "2026-02-25",
                }
            ]
        return HttpResponse(200, {}, json.dumps(payload).encode())


def collector(tmp_path, overrides=None):
    settings = Settings(
        _env_file=None, ENABLE_FMP=True, FMP_API_KEY="secret-sentinel", persist_dir=tmp_path
    )
    return LegacyLiveProvider(settings, http=FixtureHttp(overrides), now=NOW)


def test_stable_endpoints_and_source_urls_exclude_keys(tmp_path):
    provider = collector(tmp_path)
    record = provider.fmp("income-statement", "nvda")
    assert record.data[0]["revenue"] == 1000
    assert "secret-sentinel" not in record.url
    parsed = urlsplit(provider.http.calls[0])
    assert parsed.path == "/stable/income-statement"
    assert parse_qs(parsed.query)["period"] == ["annual"]
    assert parse_qs(parsed.query)["apikey"] == ["secret-sentinel"]
    with pytest.raises(ValueError, match="Unsupported"):
        provider.fmp("../admin", "NVDA")


@pytest.mark.parametrize("value", ["", "NVDA/AAPL", "https://evil.test", "NVDA?apikey=x"])
def test_invalid_symbols_rejected(value):
    with pytest.raises(ValueError):
        symbol(value)


@pytest.mark.parametrize("status", [401, 402, 403, 429, 500])
def test_entitlement_errors_are_not_empty_news_and_fallback_works(tmp_path, status):
    provider = collector(tmp_path, {"news/stock": status})
    news = provider.news("NVDA")
    assert news.provider == "Yahoo Finance RSS"
    assert news.data[0]["url"] == "https://publisher.test/nvda"
    assert str(status) in news.notices[0]
    assert "private error body" not in str(news)


@pytest.mark.parametrize(
    "payload", [{"Error Message": "private"}, [{"symbol": "OTHER"}], [], b"bad-json"]
)
def test_invalid_fmp_quote_uses_validated_yahoo_fallback(tmp_path, payload):
    provider = collector(tmp_path, {"quote": payload})
    quote = provider.quote("NVDA")
    assert quote.provider == "Yahoo Finance"
    assert quote.data[0]["price"] == 125


def test_timeout_and_invalid_yahoo_do_not_fabricate_quote(tmp_path):
    provider = collector(
        tmp_path,
        {"quote": TimeoutError("private"), "/v8/finance/chart/NVDA": {"chart": {"result": None}}},
    )
    quote = provider.quote("NVDA")
    assert not quote.data
    assert "invalid chart" in quote.issue


def test_news_distinguishes_empty_invalid_and_usable_fmp(tmp_path):
    provider = collector(
        tmp_path,
        {
            "news/stock": [
                {"symbol": "NVDA", "title": "A headline", "url": "https://publisher.test/story"}
            ]
        },
    )
    assert provider.news("NVDA").provider == "FMP"
    for rss, message in ((b"bad xml", "invalid feed"), (b"<rss/>", "no usable headlines")):
        provider = collector(tmp_path, {"news/stock": [], "/rss/headline": rss})
        result = provider.news("NVDA")
        assert not result.data
        assert message in result.issue
        assert "no matching records" in result.notices[0]


def test_history_uses_stable_then_yahoo_and_rejects_total_failure(tmp_path):
    provider = collector(tmp_path)
    frame, record = provider.history("NVDA")
    assert len(frame) == 25 and record.provider == "FMP"
    provider = collector(tmp_path, {"historical-price-eod/full": 403})
    frame, record = provider.history("NVDA")
    assert len(frame) == 25 and record.provider == "Yahoo Finance"
    assert "403" in record.notices[0]
    provider = collector(tmp_path, {"historical-price-eod/full": [], "/v8/finance/chart/NVDA": 503})
    with pytest.raises(ValueError, match="unavailable"):
        provider.history("NVDA")


def test_history_requires_valid_dated_ohlcv():
    for invalid in (
        [],
        rows()[:5],
        [dict(r, date="bad") for r in rows()],
        [dict(r, low=1000) for r in rows()],
        [dict(r, close=float("nan")) for r in rows()],
    ):
        with pytest.raises(ValueError):
            history_frame(invalid)


def test_disabled_fmp_never_transmits_key(tmp_path):
    provider = collector(tmp_path)
    provider.settings.enable_fmp = False
    assert "disabled" in provider.fmp("quote", "NVDA").issue
    assert not provider.http.calls


def test_report_dispatch_respects_shared_http_concurrency(tmp_path):
    provider = collector(tmp_path)
    fixture = provider.http
    pair = Barrier(2)

    def transport(request, _timeout, _limit):
        if urlsplit(request.url).path.removeprefix("/stable/") in {
            "quote",
            "profile",
            "income-statement",
            "balance-sheet-statement",
        }:
            pair.wait(timeout=3)
        return fixture.fetch(request)

    provider.http = SharedHttpClient(transport, max_retries=0, provider_concurrency=2)
    report = build_live_research("NVDA", str(tmp_path), provider=provider)
    content = "\n".join(part[1] for part in report)
    assert "1,000.00" in content
    assert "request failed" not in content


def test_rss_filters_unrelated_titles_and_supports_company_name(tmp_path):
    rss = b"<rss><channel><item><title>Nvidia reports results</title><link>https://publisher.test/nvda</link></item><item><title>Unrelated company results</title><link>https://publisher.test/other</link></item></channel></rss>"
    provider = collector(tmp_path, {"/rss/headline": rss})
    result = provider.news("NVDA", company_name="NVIDIA Corporation")
    assert [row["title"] for row in result.data] == ["Nvidia reports results"]


def test_report_is_built_only_from_records_with_periods_sources_and_safe_tables(tmp_path):
    provider = collector(tmp_path)
    report = build_live_research("NVDA", str(tmp_path), provider=provider)
    markdown = "\n".join(part[1] for part in report)
    assert "1,000.00" in markdown and "Net income" in markdown
    assert "2026-01-31" in markdown and "2026-02-25" in markdown
    assert (
        "subscription restricted" in markdown
        and "Not read: host_not_allowed"
        in BeautifulSoup(sanitized_markdown(markdown), "html.parser").get_text()
    )
    assert "Strong Buy" not in markdown and "partial allocation" not in markdown
    page = BeautifulSoup(sanitized_markdown(markdown), "html.parser")
    assert len(page.select("table")) >= 3
    assert page.select_one("th[scope=col]")
    snapshots = list((tmp_path / "legacy_evidence").rglob("*.txt"))
    assert len(snapshots) >= 6
    assert all("secret-sentinel" not in p.read_text() for p in snapshots)


def test_missing_data_and_hostile_profile_stay_explicit_and_escaped(tmp_path):
    provider = collector(
        tmp_path,
        {
            "income-statement": 403,
            "balance-sheet-statement": [],
            "profile": [{"symbol": "NVDA", "companyName": "<script>alert(1)</script>|Injected"}],
        },
    )
    report = build_live_research("NVDA", str(tmp_path), provider=provider)
    rendered = sanitized_markdown("\n".join(part[1] for part in report))
    assert "HTTP 403" in rendered and "Unavailable" in rendered
    assert "<script>" not in rendered
    assert "date" not in timestamp(None).lower()
    assert timestamp(10**30) == "Unavailable"


def test_technical_report_uses_real_history_without_trade_commands_or_forecasts(tmp_path):
    provider = collector(tmp_path, {"historical-price-eod/full": 403})
    report = build_technical_report("NVDA", settings=provider.settings, provider=provider)
    assert report["status"] == "success"
    assert "Yahoo Finance" in report["text"] and "USD" in report["text"]
    assert report["tech_image"].startswith("iVBORw0KGgo")
    assert report["bollinger_image"].startswith("iVBORw0KGgo")
    assert report["arima_image"] is None and report["garch_image"] is None
    assert "BUY" not in report["text"] and "Confidence:" not in report["text"]
    provider = collector(
        tmp_path, {"historical-price-eod/full": 403, "/v8/finance/chart/NVDA": 503}
    )
    assert (
        build_technical_report("NVDA", settings=provider.settings, provider=provider)["status"]
        == "error"
    )


def test_technical_report_without_currency_does_not_assume_usd(tmp_path):
    provider = collector(tmp_path, {"profile": []})
    report = build_technical_report("NVDA", settings=provider.settings, provider=provider)
    assert "currency unavailable" in report["text"]


def test_markdown_tables_keep_formatting_without_allowing_html_execution():
    result = sanitized_markdown(
        "| Metric | Value |\n| --- | --- |\n| Revenue | **100** |\n\n"
        '<table onclick="evil()"><tr><td><img src=x onerror="evil()">x</td></tr></table>'
    )
    page = BeautifulSoup(result, "html.parser")
    assert page.select_one(".report-table[tabindex='0'] strong").text == "100"
    assert "onclick" not in result and "onerror" not in result and "<img" not in result


def test_report_reads_article_and_indexes_passages_in_its_own_snapshot(tmp_path):
    from financial_ai.providers.article_reader import ReadArticle
    from financial_ai.storage.report_evidence import ReportEvidenceStore
    from types import SimpleNamespace

    reader = SimpleNamespace(
        read=lambda item, **kwargs: ReadArticle(
            item["url"],
            "NVIDIA original article",
            "2026-11-10",
            "2026-11-11",
            status="read",
            classification="publisher-labelled analysis",
            paragraphs=["NVIDIA demand increased while spending returns remain uncertain. " * 10],
            raw_html="<article>Original source body</article>",
        )
    )
    store = ReportEvidenceStore(tmp_path / "report_evidence.sqlite3")
    ident = store.create("NVDA")
    parts = build_live_research(
        "NVDA", str(tmp_path), provider=collector(tmp_path), reader=reader, scope=(store, ident)
    )
    store.finalize(ident, "NVDA", "report")
    markdown = "\n".join(p[1] for p in parts)
    assert "Read from source" in markdown and "publisher-labelled analysis" in markdown
    assert "NVIDIA demand increased" in markdown
    passages = store.search(ident, "NVDA", "spending returns", news=True)
    assert passages and passages[0]["url"] == "https://publisher.test/nvda"
    assert passages[0]["evidence_id"]
