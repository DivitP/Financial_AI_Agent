"""Risk findings that preserve adverse evidence through final composition."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import Field

from financial_ai.agents.models import AgentFinding, AgentModel


class RiskCategory(str, Enum):
    DOWNSIDE_DRIVER = "downside_driver"
    DATA_CONFLICT = "data_conflict"
    CONCENTRATION = "concentration"
    MACRO = "macro"
    ACCOUNTING = "accounting"
    THESIS_BREAKER = "thesis_breaker"


class RiskSignal(AgentModel):
    category: RiskCategory
    description: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(min_length=1)
    adverse: bool = True


class RiskAssessment(AgentModel):
    findings: list[AgentFinding]


class RiskAnalystNode:
    """Converts all adverse structured signals into visible, cited risk findings."""

    def analyze(self, signals: list[RiskSignal]) -> RiskAssessment:
        findings = [
            AgentFinding(
                summary=f"{signal.category.value.replace('_', ' ')}: {signal.description}",
                evidence_ids=list(dict.fromkeys(signal.evidence_ids)),
                limitations=["Risk evidence is retained even when other findings are favorable."],
            )
            for signal in signals
            if signal.adverse
        ]
        return RiskAssessment(findings=findings)


def compose_final_findings(
    findings: list[AgentFinding], risk_assessment: RiskAssessment
) -> list[AgentFinding]:
    """Append every adverse risk finding; callers cannot filter this required section."""

    return [*findings, *risk_assessment.findings]
