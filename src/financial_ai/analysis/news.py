"""Entity relevance, canonical clustering, and deduplicated news aggregation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum

from financial_ai.providers.news import NewsArticle, canonicalize_url


class NewsRelevance(str, Enum):
    COMPANY = "company"
    SECTOR = "sector"
    UNRELATED = "unrelated"


@dataclass(frozen=True)
class CompanyEntity:
    symbol: str
    name: str
    aliases: tuple[str, ...] = ()
    sector_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewsCluster:
    id: str
    representative: NewsArticle
    members: tuple[NewsArticle, ...]
    relevance: NewsRelevance


def classify_relevance(article: NewsArticle, entity: CompanyEntity) -> NewsRelevance:
    text = f"{article.title} {article.summary or ''}".casefold()
    names = (entity.name, *entity.aliases)
    if any(name.casefold() in text for name in names if len(name) > 2):
        return NewsRelevance.COMPANY
    symbol = re.escape(entity.symbol.upper())
    if re.search(
        rf"\${symbol}\b|\({symbol}\)", article.title.upper() + " " + (article.summary or "").upper()
    ):
        return NewsRelevance.COMPANY
    if any(term.casefold() in text for term in entity.sector_terms):
        return NewsRelevance.SECTOR
    return NewsRelevance.UNRELATED


def cluster_articles(articles: list[NewsArticle], entity: CompanyEntity) -> list[NewsCluster]:
    grouped: dict[str, list[NewsArticle]] = {}
    for article in articles:
        normalized = _cluster_text(article)
        date = article.published_at.date().isoformat() if article.published_at else "unknown-date"
        key = hashlib.sha256(f"{normalized}|{date}".encode()).hexdigest()[:16]
        grouped.setdefault(key, []).append(
            article.model_copy(update={"canonical_url": canonicalize_url(article.canonical_url)})
        )
    return [
        NewsCluster(key, members[0], tuple(members), classify_relevance(members[0], entity))
        for key, members in grouped.items()
    ]


def average_sentiment(scored_clusters: list[tuple[NewsCluster, float]]) -> float | None:
    """Each wire-story cluster contributes once, regardless of syndication count."""
    company_scores = [
        score for cluster, score in scored_clusters if cluster.relevance is NewsRelevance.COMPANY
    ]
    return sum(company_scores) / len(company_scores) if company_scores else None


def _cluster_text(article: NewsArticle) -> str:
    text = article.summary or article.title
    return re.sub(r"\W+", " ", text.casefold()).strip()
