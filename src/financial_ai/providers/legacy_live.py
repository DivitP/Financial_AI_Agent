"""Bounded live inputs for the Flask compatibility interface.

Fixed provider endpoints only; a missing entitlement never becomes an empty result.
Returned source URLs and stored records never contain API keys.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pandas as pd

from financial_ai.data.http import HttpRequest, SharedHttpClient
from financial_ai.data.safe_transport import SafeTransport
from financial_ai.providers.news import NewsFeed, NewsSource, parse_rss
from financial_ai.security import safe_link


def symbol(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,14}", value):
        raise ValueError("Enter a valid stock or ETF symbol (up to 15 characters).")
    return value


@dataclass
class LiveRecord:
    provider: str
    url: str
    retrieved_at: str
    data: list[dict] = field(default_factory=list)
    issue: str | None = None
    notices: list[str] = field(default_factory=list)


class LegacyLiveProvider:
    """Request-scoped collector: cache is bounded and successful sources are reused."""

    endpoints = {
        "quote",
        "profile",
        "income-statement",
        "balance-sheet-statement",
        "cash-flow-statement",
        "historical-price-eod/full",
        "news/stock",
    }

    def __init__(self, settings, *, http=None, now=None):
        self.settings = settings
        self.now = now or datetime.now(UTC)
        self.http = http or SharedHttpClient(
            SafeTransport(
                [
                    "financialmodelingprep.com",
                    "query1.finance.yahoo.com",
                    "finance.yahoo.com",
                    "feeds.finance.yahoo.com",
                ]
            ),
            timeout_seconds=min(settings.request_timeout_seconds, 12),
            max_retries=1,
            max_response_bytes=2_000_000,
        )

    def _record(self, provider, url, request_url):
        record = LiveRecord(provider, url, self.now.isoformat())
        try:
            response = self.http.fetch(HttpRequest(provider, request_url))
            if response.status_code != 200:
                reason = {
                    401: "credentials rejected",
                    402: "subscription restricted",
                    403: "access forbidden (endpoint or account entitlement)",
                    429: "rate limit reached",
                }.get(response.status_code, "provider unavailable")
                record.issue = f"{provider}: HTTP {response.status_code}, {reason}."
                return record, None
            return record, response.body
        except Exception:
            record.issue = f"{provider}: request failed or exceeded its limits."
            return record, None

    def fmp(self, endpoint: str, ticker: str, *, limit: int = 1) -> LiveRecord:
        ticker = symbol(ticker)
        if endpoint not in self.endpoints:
            raise ValueError("Unsupported FMP endpoint")
        if not 1 <= limit <= 5:
            raise ValueError("Financial history is limited to five annual periods")
        params: dict = {"symbols" if endpoint == "news/stock" else "symbol": ticker}
        if endpoint.endswith("statement"):
            params.update(period="annual", limit=limit)
        if endpoint == "news/stock":
            params["limit"] = 6
        if endpoint == "historical-price-eod/full":
            params["from"] = (self.now - timedelta(days=120)).date().isoformat()
        url = f"https://financialmodelingprep.com/stable/{endpoint}?{urlencode(params)}"
        key = self.settings.fmp_api_key
        if not self.settings.enable_fmp or not key:
            return LiveRecord(
                "FMP", url, self.now.isoformat(), issue="FMP is disabled or unconfigured."
            )
        record, body = self._record(
            "FMP", url, url + "&" + urlencode({"apikey": key.get_secret_value()})
        )
        if body is not None:
            try:
                data = json.loads(body)
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError("Invalid provider response")
                # Some endpoints include unrelated records; never use another symbol's facts.
                record.data = [r for r in data if str(r.get("symbol", "")).upper() == ticker]
                if not record.data:
                    record.issue = "FMP returned no matching records (not a provider-access error)."
            except (ValueError, TypeError):
                record.issue = "FMP returned an invalid response."
        return record

    def yahoo_chart(self, ticker: str) -> LiveRecord:
        ticker = symbol(ticker)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=3mo&interval=1d"
        record, body = self._record("Yahoo Finance", url, url)
        if body is not None:
            try:
                chart = json.loads(body)["chart"]["result"][0]
                if chart["meta"]["symbol"].upper() != ticker:
                    raise ValueError("Symbol mismatch")
                record.data = [chart]
            except (ValueError, KeyError, TypeError, IndexError):
                record.issue = "Yahoo Finance returned an invalid chart response."
        return record

    def quote(self, ticker: str) -> LiveRecord:
        record = self.fmp("quote", ticker)
        if record.data and finite(record.data[0].get("price"), positive=True):
            return record
        fallback = self.yahoo_chart(ticker)
        fallback.notices.append(record.issue or "FMP quote was incomplete.")
        if fallback.data:
            meta = fallback.data[0]["meta"]
            if not finite(meta.get("regularMarketPrice"), positive=True):
                fallback.data = []
                fallback.issue = "Yahoo Finance returned an invalid price."
            else:
                fallback.data = [
                    {
                        "symbol": symbol(ticker),
                        "name": meta.get("longName", ticker),
                        "price": meta["regularMarketPrice"],
                        "currency": meta.get("currency"),
                        "timestamp": meta.get("regularMarketTime"),
                        "volume": meta.get("regularMarketVolume"),
                    }
                ]
        return fallback

    def news(self, ticker: str, company_name: str | None = None) -> LiveRecord:
        record = self.fmp("news/stock", ticker)
        if record.data:
            record.data = [r for r in record.data if safe_link(r.get("url")) and r.get("title")]
            if record.data:
                return record
        ticker = symbol(ticker)
        url = f"https://finance.yahoo.com/rss/headline?{urlencode({'s': ticker})}"
        fallback, body = self._record("Yahoo Finance RSS", url, url)
        fallback.notices.append(record.issue or "FMP returned no usable article links.")
        if body is not None:
            try:
                feed = NewsFeed(
                    url=url, publisher="Yahoo Finance RSS", source=NewsSource.APPROVED_RSS
                )
                aliases = [ticker]
                words = (company_name or "").split()
                if words and len(words[0]) >= 3 and words[0].lower() not in {"the", "inc", "corp"}:
                    aliases.append(words[0])
                pattern = re.compile(
                    r"(?<![A-Z0-9])(?:"
                    + "|".join(re.escape(a) for a in aliases)
                    + r")(?![A-Z0-9])",
                    re.I,
                )
                fallback.data = [
                    {
                        "title": article.title,
                        "url": article.canonical_url,
                        "publishedDate": article.published_at.isoformat()
                        if article.published_at
                        else None,
                        "publisher": article.publisher,
                    }
                    for article in parse_rss(body, feed, self.now)
                    if safe_link(article.canonical_url) and pattern.search(article.title)
                ][:6]
                if not fallback.data:
                    fallback.issue = "Yahoo Finance RSS returned no usable headlines."
            except Exception:
                fallback.issue = "Yahoo Finance RSS returned an invalid feed."
        return fallback

    def history(self, ticker: str) -> tuple[pd.DataFrame, LiveRecord]:
        record = self.fmp("historical-price-eod/full", ticker)
        try:
            frame = history_frame(record.data)
            record.notices.append(
                "Provider EOD OHLCV; corporate-action adjustment is not verified."
            )
            return frame, record
        except ValueError:
            pass
        fallback = self.yahoo_chart(ticker)
        fallback.notices.append(record.issue or "FMP history was incomplete or invalid.")
        try:
            chart = fallback.data[0]
            quotes = chart["indicators"]["quote"][0]
            rows = [
                dict(
                    date=datetime.fromtimestamp(stamp, UTC).isoformat(),
                    **{
                        field: quotes[field][i]
                        for field in ("open", "high", "low", "close", "volume")
                    },
                )
                for i, stamp in enumerate(chart["timestamp"])
            ]
            frame = history_frame(rows)
        except (ValueError, KeyError, TypeError, IndexError):
            raise ValueError(
                "Price history unavailable from FMP and Yahoo Finance. Check provider access and retry."
            ) from None
        fallback.notices.append(
            "Yahoo chart OHLCV as supplied; corporate-action adjustment is not verified."
        )
        return frame, fallback


def finite(value, *, positive=False):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and (not positive or value > 0)
    )


def history_frame(rows: list[dict]) -> pd.DataFrame:
    valid = [
        r
        for r in rows
        if r.get("date")
        and all(finite(r.get(k), positive=True) for k in ("open", "high", "low", "close"))
        and finite(r.get("volume"))
        and r["volume"] >= 0
        and r["low"] <= min(r["open"], r["close"]) <= max(r["open"], r["close"]) <= r["high"]
    ]
    frame = pd.DataFrame(valid)
    if len(frame) < 20:
        raise ValueError("Insufficient valid history (20 observations required)")
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce", format="ISO8601")
    frame = frame.dropna(subset=["date"]).drop_duplicates("date").set_index("date").sort_index()
    if len(frame) < 20:
        raise ValueError("Insufficient unique dated observations")
    return frame[["open", "high", "low", "close", "volume"]].rename(columns=str.title)
