"""Explicit free-source collector; external requests use the shared safety boundary."""

import json
import math
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from financial_ai.data.http import HttpRequest, SharedHttpClient
from financial_ai.providers.sec import SecFilingCollector
from financial_ai.providers.news import NewsFeed, NewsSource, CompanyNewsCollector
from financial_ai.providers.collected import CollectedLane


class LiveCollector:
    def __init__(self, settings, *, http=None):
        from financial_ai.data.safe_transport import SafeTransport

        self.settings = settings
        self.http = http or SharedHttpClient(
            SafeTransport([*settings.document_allowed_hosts, "query1.finance.yahoo.com"]),
            timeout_seconds=settings.request_timeout_seconds,
            cache_ttl_seconds=settings.cache_ttl_seconds,
            max_response_bytes=20_000_000,
            user_agent=settings.sec_user_agent,
        )
        self.market = None
        self.filings = None

    def collect(self, lane, run):
        now = datetime.now(UTC)
        symbol = run["symbol"]
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?range=1y&interval=1d"
        if lane in {"instrument", "quote", "ohlcv"}:
            if self.market is None:
                response = self.http.fetch(HttpRequest("yahoo", url))
                if response.status_code != 200:
                    raise ValueError("Market response unavailable")
                self.market = json.loads(response.body)["chart"]["result"][0]
            meta = self.market["meta"]
            if meta["instrumentType"] not in {"EQUITY", "ETF"}:
                raise ValueError("Only equity and ETF instruments are supported")
            currency, zone = meta["currency"], meta["exchangeTimezoneName"]
            published = datetime.fromtimestamp(meta["regularMarketTime"], UTC)
            common = {"currency": currency, "timezone": zone, "adjustment_policy": "raw"}
            if lane == "instrument":
                payload = {
                    **common,
                    "name": meta.get("longName") or meta.get("shortName") or symbol,
                    "exchange": meta["exchangeName"],
                    "asset_type": meta["instrumentType"].lower(),
                }
                text = f"{symbol} is reported as {meta['instrumentType']} on {meta['exchangeName']} in {currency}."
            elif lane == "quote":
                price = float(meta["regularMarketPrice"])
                if not math.isfinite(price) or price <= 0:
                    raise ValueError("Invalid market price")
                payload = {**common, "price": price, "as_of": published.isoformat()}
                text = f"{symbol} reported market price: {price} {currency}, as of {published.isoformat()}."
            else:
                adjusted = self.market["indicators"]["adjclose"][0]["adjclose"]
                candles = []
                for i, stamp in enumerate(self.market["timestamp"]):
                    close = adjusted[i]
                    if close is None:
                        continue
                    if not math.isfinite(close) or close <= 0:
                        raise ValueError("Invalid historical price")
                    candles.append(
                        {
                            "timestamp": datetime.fromtimestamp(stamp, UTC).isoformat(),
                            "close": close,
                            "volume": None,
                        }
                    )
                if len(candles) < 20:
                    raise ValueError("Insufficient historical prices")
                payload = {
                    **common,
                    "candles": candles,
                    "adjustment_policy": "provider_adjusted_close",
                }
                text = f"{symbol} historical adjusted closes in {currency}: " + "; ".join(
                    f"{c['timestamp']}: {c['close']}" for c in candles[-30:]
                )
            return CollectedLane(
                provider="yahoo",
                url=url,
                retrieved_at=now,
                published_at=published,
                payload=payload,
                text=text,
                limitations=[
                    "Provider data may be delayed; no trading or calibrated forecast recommendation."
                ],
            )
        sec = SecFilingCollector(self.http)
        if lane in {"filings", "statements"}:
            if self.filings is None:
                self.filings = sec.collect_filings(symbol)
            if not self.filings:
                raise ValueError("No supported SEC company filings available")
            latest = max(self.filings, key=lambda filing: filing.filed_at)
            if lane == "filings":
                return CollectedLane(
                    provider="sec",
                    url=latest.url,
                    retrieved_at=now,
                    published_at=latest.filed_at,
                    payload={"items": [f.model_dump(mode="json") for f in self.filings[:20]]},
                    text=f"{symbol} filed {latest.form}, accession {latest.accession_number}, on {latest.filed_at.isoformat()}.",
                    limitations=["Filing metadata only; full filing text has not been downloaded."],
                )
            facts = sec.collect_xbrl_facts(
                UUID(str(run["instrument_id"])),
                latest.cik,
                {f.accession_number: f.accepted_at for f in self.filings if f.accepted_at},
            )
            facts = sorted(facts, key=lambda f: (f.filed_at, f.period_end), reverse=True)
            if not facts:
                raise ValueError("No normalized financial statement facts available")
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{latest.cik}.json"
            return CollectedLane(
                provider="sec",
                url=url,
                retrieved_at=now,
                published_at=max(f.filed_at for f in facts),
                payload={"facts": [f.model_dump(mode="json") for f in facts]},
                text="\n".join(
                    f"{f.taxonomy}:{f.tag} = {f.value} {f.unit}; period {f.period_start} to {f.period_end}; accession {f.accession_number}."
                    for f in facts[:10]
                ),
                limitations=[
                    "Reported facts retain accession identities; periods are not assumed comparable."
                ],
            )
        if lane == "news":
            if not self.settings.research_news_feeds:
                raise ValueError("Configure approved company RSS sources for news collection")
            feed = self.settings.research_news_feeds[0]
            articles = CompanyNewsCollector(self.http).rss(
                NewsFeed(
                    url=feed, publisher="Configured publisher", source=NewsSource.APPROVED_RSS
                ),
                now,
            )
            # Retain explicitly matching headlines only; do not treat broad feed volume as sentiment.
            selected = [a for a in articles if symbol in a.title.upper().split()][:5]
            if not selected:
                raise ValueError("No unambiguous ticker-specific headlines found in approved feed")
            article = selected[0]
            if article.published_at is None:
                raise ValueError("Article publication time unavailable")
            return CollectedLane(
                provider="rss",
                url=article.canonical_url,
                retrieved_at=now,
                published_at=article.published_at,
                text=article.title,
                payload={
                    "articles": [article.model_dump(mode="json")],
                    "discovered_from": feed,
                },
                limitations=[
                    "Publisher-feed headline only; no article-body or sentiment conclusion."
                ],
            )
        raise ValueError("Unsupported collection lane")
