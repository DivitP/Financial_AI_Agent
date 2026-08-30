"""Explainable research-data quality grading without fabricated confidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID


class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class QualityRecord:
    key: str
    observed_at: datetime
    provider: str
    value: float | None
    filing_accession: str | None = None


@dataclass(frozen=True)
class QualityClaim:
    statement: str
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class DataQualityReport:
    grade: QualityGrade
    reasons: tuple[str, ...]


def assess_data_quality(
    *,
    as_of: datetime,
    required_lanes: tuple[str, ...],
    completed_lanes: tuple[str, ...],
    records: tuple[QualityRecord, ...],
    claims: tuple[QualityClaim, ...],
    evidence_ids: frozenset[UUID],
    max_age: timedelta = timedelta(days=30),
) -> DataQualityReport:
    """Grade only documented coverage, freshness, consistency, and claim support."""
    reasons: list[str] = []
    missing = sorted(set(required_lanes) - set(completed_lanes))
    if missing:
        reasons.append(f"Incomplete research lanes: {', '.join(missing)}.")
    if not records:
        reasons.append("No observed records were collected.")
    for record in records:
        if as_of - record.observed_at > max_age:
            reasons.append(f"Stale {record.key} observation from {record.provider}.")
    keys = {record.key for record in records}
    if "period_current" in keys and "period_prior" not in keys:
        reasons.append("Missing prior comparison period.")
    for key in keys:
        same_key = [record for record in records if record.key == key and record.value is not None]
        if (
            len({record.provider for record in same_key}) > 1
            and len({record.value for record in same_key}) > 1
        ):
            reasons.append(f"Conflicting provider values for {key}.")
        accessions = {record.filing_accession for record in same_key if record.filing_accession}
        if len(accessions) > 1:
            reasons.append(f"Restated {key} values retained from multiple filings.")
    for claim in claims:
        if not claim.evidence_ids or not set(claim.evidence_ids).issubset(evidence_ids):
            reasons.append(f"Unsupported claim: {claim.statement}")
    if not reasons:
        grade = QualityGrade.A
    elif len(reasons) == 1:
        grade = QualityGrade.B
    elif len(reasons) <= 3:
        grade = QualityGrade.C
    else:
        grade = QualityGrade.D if records else QualityGrade.INSUFFICIENT
    return DataQualityReport(grade, tuple(dict.fromkeys(reasons)))
