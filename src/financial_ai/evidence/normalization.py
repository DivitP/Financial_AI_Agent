"""Convert provider records into stable, cited evidence records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from financial_ai.domain.models import Evidence, EvidenceKind, Freshness, SourceDocument, SourceTier


@dataclass(frozen=True)
class NormalizedEvidence:
    source_document: SourceDocument
    evidence: Evidence


class EvidenceNormalizer:
    def normalize(
        self,
        *,
        run_id: UUID,
        provider: str,
        kind: EvidenceKind,
        exact_url: str,
        title: str,
        content: str,
        retrieved_at: datetime,
        published_at: datetime | None = None,
        source_tier: SourceTier = SourceTier.OFFICIAL,
        terms_classification: str = "provider-terms-required",
    ) -> NormalizedEvidence:
        _require_aware(retrieved_at)
        if published_at is not None:
            _require_aware(published_at)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        source_id = uuid5(NAMESPACE_URL, f"{provider}:{exact_url}:{content_hash}")
        evidence_id = uuid5(NAMESPACE_URL, f"{run_id}:{provider}:{exact_url}:{content_hash}")
        source = SourceDocument(
            id=source_id,
            provider=provider,
            canonical_url=exact_url,
            title=title,
            published_at=published_at,
            retrieved_at=retrieved_at,
            content_hash=content_hash,
            terms_classification=terms_classification,
        )
        evidence = Evidence(
            id=evidence_id,
            run_id=run_id,
            source_document_id=source_id,
            provider=provider,
            kind=kind,
            retrieved_at=retrieved_at,
            locator=exact_url,
            content_hash=content_hash,
            excerpt=content[:500] or None,
            source_tier=source_tier,
            freshness=_freshness(published_at, retrieved_at),
            exact_url=exact_url,
        )
        return NormalizedEvidence(source, evidence)


def _freshness(published_at: datetime | None, retrieved_at: datetime) -> Freshness:
    if published_at is None:
        return Freshness.UNKNOWN
    age = retrieved_at - published_at
    if age <= timedelta(days=7):
        return Freshness.FRESH
    if age <= timedelta(days=90):
        return Freshness.AGING
    return Freshness.STALE


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamps must include a timezone offset")
