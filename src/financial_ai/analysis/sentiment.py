"""Local financial sentiment with inspectable spans and uncertainty."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from financial_ai.providers.news import NewsArticle


class EventCategory(str, Enum):
    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    M_AND_A = "m_and_a"
    REGULATORY = "regulatory"
    CAPITAL_RETURN = "capital_return"
    MANAGEMENT = "management"
    OPERATIONS = "operations"
    OTHER = "other"


@dataclass(frozen=True)
class SentimentResult:
    article_url: str
    publisher: str
    text_span: str
    label: str
    score: float
    confidence: float
    uncertainty: float
    event_categories: tuple[EventCategory, ...]
    time_decay: float


@dataclass(frozen=True)
class SentimentSummary:
    score: float | None
    uncertainty: float | None
    source_diversity: float
    article_count: int


Classifier = Callable[[str], list[dict[str, Any]]]


class LocalFinanceSentiment:
    """Lazy local FinBERT loader; tests inject a classifier and never download a model."""

    def __init__(
        self, classifier: Classifier | None = None, *, model_id: str = "ProsusAI/finbert"
    ) -> None:
        self._classifier = classifier
        self.model_id = model_id

    def analyze(
        self, article: NewsArticle, *, as_of: datetime, half_life_days: float = 7.0
    ) -> SentimentResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone offset")
        span = _relevant_span(article)
        result = self._model()(span)[0]
        label = str(result["label"]).lower()
        confidence = float(result["score"])
        score = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}.get(label, 0.0)
        age_days = max(
            0.0, (as_of - (article.published_at or article.retrieved_at)).total_seconds() / 86_400
        )
        return SentimentResult(
            article_url=article.canonical_url,
            publisher=article.publisher,
            text_span=span,
            label=label,
            score=score,
            confidence=confidence,
            uncertainty=1.0 - confidence,
            event_categories=classify_events(span),
            time_decay=math.exp(-age_days / half_life_days),
        )

    def _model(self) -> Classifier:
        if self._classifier is None:
            try:
                from transformers import pipeline
            except ImportError as error:
                raise RuntimeError(
                    "Local sentiment requires the 'sentiment' dependency group: uv sync --extra sentiment"
                ) from error
            self._classifier = pipeline("text-classification", model=self.model_id)  # type: ignore[assignment]
        return self._classifier


def classify_events(text: str) -> tuple[EventCategory, ...]:
    lower = text.casefold()
    rules = {
        EventCategory.EARNINGS: ("earnings", "quarter results", "eps"),
        EventCategory.GUIDANCE: ("guidance", "outlook", "forecast"),
        EventCategory.M_AND_A: ("acquire", "merger", "takeover"),
        EventCategory.REGULATORY: ("sec", "regulator", "investigation", "lawsuit"),
        EventCategory.CAPITAL_RETURN: ("dividend", "buyback", "repurchase"),
        EventCategory.MANAGEMENT: ("ceo", "chief executive", "appoint"),
        EventCategory.OPERATIONS: ("launch", "production", "recall"),
    }
    matches = tuple(
        category for category, terms in rules.items() if any(term in lower for term in terms)
    )
    return matches or (EventCategory.OTHER,)


def summarize_sentiment(results: list[SentimentResult]) -> SentimentSummary:
    if not results:
        return SentimentSummary(None, None, 0.0, 0)
    weights = [result.confidence * result.time_decay for result in results]
    total_weight = sum(weights)
    score = (
        sum(result.score * weight for result, weight in zip(results, weights, strict=True))
        / total_weight
        if total_weight
        else 0.0
    )
    diversity = len({result.publisher.casefold() for result in results}) / len(results)
    uncertainty = min(
        1.0, sum(result.uncertainty for result in results) / len(results) + (1 - diversity) * 0.25
    )
    return SentimentSummary(score, uncertainty, diversity, len(results))


def _relevant_span(article: NewsArticle) -> str:
    return f"{article.title}. {article.summary or ''}".strip()[:600]
