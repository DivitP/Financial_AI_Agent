"""Offline benchmark metrics; these scores are not investment confidence."""

from collections.abc import Mapping, Sequence
from math import isfinite


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if k < 1 or not relevant:
        raise ValueError("Recall requires positive k and nonempty relevance labels")
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    if not relevant:
        raise ValueError("MRR requires nonempty relevance labels")
    return next((1 / rank for rank, item in enumerate(ranked, 1) if item in relevant), 0.0)


def answer_scores(
    claims: list[dict], sources: Mapping[str, dict], relevant: set[str]
) -> dict[str, float]:
    """Citation precision includes relevance; support additionally checks exact quoted text."""
    citations = supported = 0
    for claim in claims:
        citation = claim.get("citation", {})
        key = citation.get("chunk_id")
        source = sources.get(key)
        valid = (
            source is not None
            and key in relevant
            and all(
                citation.get(field) == source[source_field]
                for field, source_field in (("evidence_id", "evidence_id"), ("url", "source_url"))
            )
        )
        citations += bool(valid)
        supported += bool(
            source is not None and valid and claim.get("text") and claim["text"] in source["text"]
        )
    # Abstentions cannot receive perfect answer-quality scores by emitting nothing.
    return {
        "citation_precision": citations / len(claims) if claims else 0.0,
        "unsupported_claim_rate": 1 - supported / len(claims) if claims else 0.0,
    }


def enforce_thresholds(scores: Mapping[str, float], thresholds: Mapping[str, dict]) -> None:
    failures = []
    for name, bounds in thresholds.items():
        value = scores.get(name, float("nan"))
        if not isfinite(value) or value < bounds.get("min", 0) or value > bounds.get("max", 1):
            failures.append(f"{name}={value}: required {bounds}")
    if failures:
        raise AssertionError("RAG evaluation gate failed: " + "; ".join(failures))
