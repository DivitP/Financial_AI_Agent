"""Evidence-first news and event interpretation without volume-based conclusions."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import Field

from financial_ai.agents.models import AgentFinding, AgentModel


class EventDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class EventEvidence(AgentModel):
    evidence_id: UUID
    source_key: str = Field(min_length=1)
    category: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    direction: EventDirection
    material: bool = True


class NewsEventAnalystNode:
    """Creates one conclusion per event category from distinct evidence records."""

    def analyze(self, events: list[EventEvidence]) -> list[AgentFinding]:
        used: set[UUID] = set()
        findings: list[AgentFinding] = []
        for category in sorted({event.category for event in events if event.material}):
            supporting: list[EventEvidence] = []
            source_keys: set[str] = set()
            for event in events:
                if (
                    event.material
                    and event.category == category
                    and event.evidence_id not in used
                    and event.source_key not in source_keys
                ):
                    supporting.append(event)
                    source_keys.add(event.source_key)
            if not supporting:
                continue
            evidence_ids = [item.evidence_id for item in supporting]
            used.update(evidence_ids)
            directions = {item.direction for item in supporting}
            direction = (
                directions.pop().value if len(directions) == 1 else EventDirection.MIXED.value
            )
            findings.append(
                AgentFinding(
                    summary=(
                        f"{category.title()} developments have {direction} disclosed implications "
                        "in the cited source material."
                    ),
                    evidence_ids=evidence_ids,
                    limitations=[
                        "Article count is not treated as a measure of investment strength.",
                        "Sentiment and event direction are contextual, not price forecasts.",
                    ],
                )
            )
        return findings
