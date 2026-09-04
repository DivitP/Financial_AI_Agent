"""Composable, durable reports whose material findings always retain exact evidence links."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from financial_ai.agents.models import AgentFinding, AgentModel
from financial_ai.storage.repositories import ResearchRepository


class EvidenceLink(AgentModel):
    evidence_id: UUID
    exact_url: str = Field(pattern=r"^https?://")


class ReportSection(AgentModel):
    title: str = Field(min_length=1)
    findings: list[AgentFinding] = Field(min_length=1)


class EvidenceBackedReport(AgentModel):
    id: UUID
    run_id: UUID
    version: int = Field(ge=1)
    as_of: datetime
    model_configuration: dict[str, str]
    decision_brief: list[str] = Field(min_length=1)
    sections: list[ReportSection] = Field(min_length=1)
    evidence_links: list[EvidenceLink] = Field(default_factory=list)

    @model_validator(mode="after")
    def every_material_claim_has_an_exact_link(self) -> "EvidenceBackedReport":
        linked = {item.evidence_id for item in self.evidence_links}
        cited = {
            evidence_id
            for section in self.sections
            for finding in section.findings
            for evidence_id in finding.evidence_ids
        }
        missing = cited - linked
        if missing:
            raise ValueError("every material finding must link to exact evidence")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone offset")
        return self

    def persistence_sections(self) -> list[dict[str, object]]:
        return [section.model_dump(mode="json") for section in self.sections]


class EvidenceBackedReportComposer:
    """Builds a brief and detailed sections from already-verified structured findings."""

    def compose(
        self,
        *,
        run_id: UUID,
        sections: dict[str, list[AgentFinding]],
        evidence_links: list[EvidenceLink],
        as_of: datetime,
        model_config: dict[str, str] | None = None,
        version: int = 1,
    ) -> EvidenceBackedReport:
        detailed = [
            ReportSection(title=title, findings=findings)
            for title, findings in sections.items()
            if findings
        ]
        if not detailed:
            raise ValueError("report composition requires verified findings")
        return EvidenceBackedReport(
            id=uuid4(),
            run_id=run_id,
            version=version,
            as_of=as_of,
            model_configuration=model_config or {"composer": "deterministic-v1"},
            decision_brief=[
                finding.summary for section in detailed for finding in section.findings
            ][:5],
            sections=detailed,
            evidence_links=evidence_links,
        )

    def persist(self, report: EvidenceBackedReport, repository: ResearchRepository) -> None:
        repository.upsert_report(
            report_id=report.id,
            run_id=report.run_id,
            version=report.version,
            as_of=report.as_of,
            model_config=report.model_configuration,
            decision_brief=report.decision_brief,
            sections=report.persistence_sections(),
            evidence_links={link.evidence_id: link.exact_url for link in report.evidence_links},
        )
