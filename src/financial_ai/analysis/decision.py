"""Evidence-first catalysts, risks, scenarios, and thesis invalidation framework."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from uuid import UUID


class EvidenceStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    UNSUPPORTED = "unsupported"


class ScenarioName(str, Enum):
    BULL = "bull"
    BASE = "base"
    BEAR = "bear"


@dataclass(frozen=True)
class RegisterItem:
    title: str
    due_at: datetime | None
    description: str
    evidence_ids: tuple[UUID, ...]
    evidence_strength: EvidenceStrength

    def __post_init__(self) -> None:
        if self.due_at and (self.due_at.tzinfo is None or self.due_at.utcoffset() is None):
            raise ValueError("due_at must include a timezone offset")
        if self.evidence_strength is EvidenceStrength.UNSUPPORTED and self.evidence_ids:
            raise ValueError("unsupported register items cannot cite evidence")
        if self.evidence_strength is not EvidenceStrength.UNSUPPORTED and not self.evidence_ids:
            raise ValueError("supported register items require evidence IDs")


@dataclass(frozen=True)
class ThesisInvalidation:
    condition: str
    evidence_ids: tuple[UUID, ...]
    monitoring_metric: str | None = None


@dataclass(frozen=True)
class Scenario:
    name: ScenarioName
    narrative: str
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[ThesisInvalidation, ...]
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class SensitivityRow:
    driver: str
    downside: str
    base: str
    upside: str
    unit: str
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class DecisionFramework:
    catalysts: tuple[RegisterItem, ...]
    risks: tuple[RegisterItem, ...]
    scenarios: tuple[Scenario, ...]
    sensitivities: tuple[SensitivityRow, ...]

    def __post_init__(self) -> None:
        names = {scenario.name for scenario in self.scenarios}
        if names != set(ScenarioName):
            raise ValueError("decision framework requires exactly bull, base, and bear scenarios")


def evidence_strength(
    evidence_ids: tuple[UUID, ...], primary_source_count: int
) -> EvidenceStrength:
    if not evidence_ids:
        return EvidenceStrength.UNSUPPORTED
    if primary_source_count >= 2:
        return EvidenceStrength.STRONG
    if primary_source_count == 1:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.WEAK


def scenario_probabilities_are_omitted() -> bool:
    """Guardrail used by tests and serializers until calibrated scenario models exist."""
    return "probability" not in {field.name for field in fields(Scenario)}
