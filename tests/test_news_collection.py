from __future__ import annotations

from datetime import UTC, datetime

from financial_ai.analysis.news import (
    CompanyEntity,
    NewsRelevance,
    average_sentiment,
    classify_relevance,
    cluster_articles,
)
from financial_ai.data.http import HttpResponse, SharedHttpClient
from financial_ai.providers.news import (
    CompanyNewsCollector,
    NewsArticle,
    NewsFeed,
    NewsSource,
    canonicalize_url,
)


NOW = datetime(2026, 8, 21, tzinfo=UTC)


def test_rss_and_gdelt_records_retain_required_article_provenance() -> None:
    rss = b"""<rss><channel><item><title>Apple reports results</title><link>https://ir.example/aapl?utm_source=x</link><dc:creator xmlns:dc='http://purl.org/dc/elements/1.1/'>Investor Relations</dc:creator><pubDate>Fri, 21 Aug 2026 13:00:00 GMT</pubDate><description>Results release</description></item></channel></rss>"""
    gdelt = b'{"articles":[{"url":"https://news.example/story?fbclid=x","title":"Apple coverage","domain":"news.example","seendate":"20260821T140000Z"}]}'
    responses = [HttpResponse(200, {}, rss), HttpResponse(200, {}, gdelt)]
    collector = CompanyNewsCollector(SharedHttpClient(lambda *_: responses.pop(0)))
    ir = collector.rss(
        NewsFeed(url="https://ir.example/rss", publisher="Apple IR", source=NewsSource.COMPANY_IR),
        NOW,
    )
    indexed = collector.gdelt("Apple", NOW)
    assert ir[0].canonical_url == "https://ir.example/aapl"
    assert ir[0].author == "Investor Relations" and ir[0].published_at and ir[0].retrieved_at == NOW
    assert indexed[0].canonical_url == "https://news.example/story"


def test_canonical_syndication_clusters_once_and_rejects_bare_ticker_collisions() -> None:
    entity = CompanyEntity("CAT", "Caterpillar Inc.", ("Caterpillar",), ("construction equipment",))
    first = NewsArticle(
        canonical_url="https://wire.example/a?utm_campaign=x",
        publisher="Wire",
        title="Caterpillar raises outlook",
        published_at=NOW,
        retrieved_at=NOW,
        summary="Caterpillar raises outlook after results.",
        source=NewsSource.APPROVED_RSS,
    )
    syndicated = first.model_copy(
        update={"canonical_url": "https://publisher.example/reprint", "publisher": "Reprint"}
    )
    clusters = cluster_articles([first, syndicated], entity)
    assert len(clusters) == 1 and len(clusters[0].members) == 2
    assert average_sentiment([(clusters[0], 0.8)]) == 0.8
    collision = first.model_copy(
        update={"title": "A cat sits on construction equipment", "summary": None}
    )
    assert classify_relevance(collision, entity) is NewsRelevance.SECTOR
    assert (
        canonicalize_url("HTTPS://Example.com/story/?gclid=x&id=7#top")
        == "https://example.com/story?id=7"
    )
