"""Closed-world, asset-aware selection of research analysis lanes."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from financial_ai.agents.models import AgentModel
from financial_ai.domain.models import AssetType, EvidenceKind


class ResearchHorizon(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class AnalysisLane(str, Enum):
    MARKET = "market"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    VALUATION = "valuation"
    EARNINGS = "earnings"
    PEERS = "peers"
    EVENTS = "events"
    ETF = "etf"
    THESIS = "thesis"


APPROVED_PROVIDERS = frozenset({"sec", "openbb", "yfinance", "fmp", "gdelt", "rss"})


class PlannedAnalysis(AgentModel):
    lane: AnalysisLane
    providers: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def only_approved_providers(self) -> "PlannedAnalysis":
        unknown = set(self.providers) - APPROVED_PROVIDERS
        if unknown:
            raise ValueError(f"unapproved providers in plan: {', '.join(sorted(unknown))}")
        return self


class ResearchPlan(AgentModel):
    asset_type: AssetType
    horizon: ResearchHorizon
    analyses: list[PlannedAnalysis] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bounded_unique_lanes(self) -> "ResearchPlan":
        lanes = [item.lane for item in self.analyses]
        if len(lanes) != len(set(lanes)):
            raise ValueError("research plans cannot repeat analysis lanes")
        if self.asset_type is AssetType.ETF and any(
            lane in lanes
            for lane in (AnalysisLane.FUNDAMENTAL, AnalysisLane.EARNINGS, AnalysisLane.PEERS)
        ):
            raise ValueError("ETF plans cannot include corporate-only analyses")
        return self


class AssetAwareResearchPlanner:
    """Selects only evidence-supported, registered analyses; it never invokes tools."""

    def plan(
        self,
        asset_type: AssetType,
        horizon: ResearchHorizon,
        available_evidence: set[EvidenceKind],
        thesis: str | None = None,
    ) -> ResearchPlan:
        analyses = [
            PlannedAnalysis(
                lane=AnalysisLane.MARKET, providers=["openbb", "yfinance"], reason="price evidence"
            ),
            PlannedAnalysis(
                lane=AnalysisLane.TECHNICAL,
                providers=[],
                reason="deterministic market regime analysis",
            ),
        ]
        has_news = bool(
            {EvidenceKind.NEWS_ARTICLE, EvidenceKind.PRESS_RELEASE} & available_evidence
        )
        if has_news:
            analyses.append(
                PlannedAnalysis(
                    lane=AnalysisLane.EVENTS, providers=["gdelt", "rss"], reason="news evidence"
                )
            )
        if asset_type is AssetType.ETF:
            if EvidenceKind.DATASET in available_evidence:
                analyses.append(
                    PlannedAnalysis(
                        lane=AnalysisLane.ETF, providers=["openbb"], reason="fund holdings data"
                    )
                )
        else:
            has_financials = bool({EvidenceKind.FILING, EvidenceKind.DATASET} & available_evidence)
            if has_financials and horizon is not ResearchHorizon.SHORT:
                analyses.extend(
                    [
                        PlannedAnalysis(
                            lane=AnalysisLane.FUNDAMENTAL,
                            providers=["sec"],
                            reason="structured statement evidence",
                        ),
                        PlannedAnalysis(
                            lane=AnalysisLane.VALUATION,
                            providers=[],
                            reason="market and financial evidence",
                        ),
                    ]
                )
            if (
                EvidenceKind.ANALYST_REPORT in available_evidence
                and horizon is not ResearchHorizon.SHORT
            ):
                analyses.append(
                    PlannedAnalysis(
                        lane=AnalysisLane.EARNINGS, providers=["fmp"], reason="public estimates"
                    )
                )
            if EvidenceKind.DATASET in available_evidence and horizon is ResearchHorizon.LONG:
                analyses.append(
                    PlannedAnalysis(
                        lane=AnalysisLane.PEERS, providers=[], reason="peer metric evidence"
                    )
                )
        if thesis and thesis.strip():
            analyses.append(
                PlannedAnalysis(
                    lane=AnalysisLane.THESIS, providers=[], reason="user-supplied thesis"
                )
            )
        return ResearchPlan(asset_type=asset_type, horizon=horizon, analyses=analyses)
