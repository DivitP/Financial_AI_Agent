"""Free-source company-news collection with durable article provenance."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from enum import Enum
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, model_validator

from financial_ai.data.http import HttpRequest, SharedHttpClient


class NewsSource(str, Enum):
    COMPANY_IR = "company_ir"
    OPENBB = "openbb"
    GDELT = "gdelt"
    APPROVED_RSS = "approved_rss"


class NewsArticle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    canonical_url: str
    publisher: str
    author: str | None = None
    title: str
    published_at: datetime | None = None
    retrieved_at: datetime
    summary: str | None = None
    source: NewsSource

    @model_validator(mode="after")
    def validate_times(self) -> "NewsArticle":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone offset")
        if self.published_at and (
            self.published_at.tzinfo is None or self.published_at.utcoffset() is None
        ):
            raise ValueError("published_at must include a timezone offset")
        return self


class NewsFeed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: str
    publisher: str
    source: NewsSource


OpenBBNewsFetcher = Callable[[], Iterable[NewsArticle]]


class CompanyNewsCollector:
    """Collection only: search/discovery URLs never become evidence by themselves."""

    def __init__(self, http: SharedHttpClient) -> None:
        self.http = http

    def rss(self, feed: NewsFeed, retrieved_at: datetime) -> list[NewsArticle]:
        response = self.http.fetch(HttpRequest(provider=feed.source.value, url=feed.url))
        return parse_rss(response.body, feed, retrieved_at)

    def gdelt(self, query: str, retrieved_at: datetime, max_records: int = 50) -> list[NewsArticle]:
        url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(
            {"query": query, "mode": "artlist", "format": "json", "maxrecords": max_records}
        )
        response = self.http.fetch(HttpRequest(provider="gdelt", url=url))
        return parse_gdelt(response.body, retrieved_at)

    @staticmethod
    def openbb(fetcher: OpenBBNewsFetcher) -> list[NewsArticle]:
        """Use only an explicitly selected OpenBB source; do not silently substitute one."""
        return list(fetcher())


def parse_rss(payload: bytes, feed: NewsFeed, retrieved_at: datetime) -> list[NewsArticle]:
    root = ElementTree.fromstring(payload)
    articles: list[NewsArticle] = []
    for item in root.findall(".//item"):
        link = _text(item, "link")
        title = _text(item, "title")
        if not link or not title:
            continue
        articles.append(
            NewsArticle(
                canonical_url=canonicalize_url(link),
                publisher=feed.publisher,
                author=_text(item, "{http://purl.org/dc/elements/1.1/}creator")
                or _text(item, "author"),
                title=title,
                published_at=_parse_time(_text(item, "pubDate") or _text(item, "published")),
                retrieved_at=retrieved_at,
                summary=_text(item, "description"),
                source=feed.source,
            )
        )
    return articles


def parse_gdelt(payload: bytes, retrieved_at: datetime) -> list[NewsArticle]:
    records = json.loads(payload.decode("utf-8")).get("articles", [])
    return [
        NewsArticle(
            canonical_url=canonicalize_url(str(item["url"])),
            publisher=str(item.get("domain") or "GDELT indexed source"),
            author=None,
            title=str(item.get("title") or "Untitled article"),
            published_at=_parse_time(item.get("seendate")),
            retrieved_at=retrieved_at,
            source=NewsSource.GDELT,
        )
        for item in records
        if item.get("url")
    ]


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
        ],
        doseq=True,
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _text(item: ElementTree.Element, name: str) -> str | None:
    value = item.findtext(name)
    return value.strip() if value else None


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = parsedate_to_datetime(text)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
