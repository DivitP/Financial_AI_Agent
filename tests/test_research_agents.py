from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from financial_ai.agents.events import EventDirection, EventEvidence, NewsEventAnalystNode
from financial_ai.agents.fundamental import FundamentalAnalystNode, verify_numeric_claims
from financial_ai.agents.planner import (
    AnalysisLane,
    AssetAwareResearchPlanner,
    PlannedAnalysis,
    ResearchHorizon,
)
from financial_ai.domain.models import AssetType, EvidenceKind, MetricObservation


def test_asset_aware_planner_is_bounded_and_excludes_corporate_lanes_for_etfs() -> None:
    planner = AssetAwareResearchPlanner()
    plan = planner.plan(
        AssetType.ETF,
        ResearchHorizon.LONG,
        {EvidenceKind.DATASET, EvidenceKind.NEWS_ARTICLE},
        thesis="Prefer diversified exposure",
    )
    lanes = {item.lane for item in plan.analyses}
    assert AnalysisLane.ETF in lanes
    assert AnalysisLane.FUNDAMENTAL not in lanes
    assert len(plan.analyses) <= 8
    with pytest.raises(ValueError, match="unapproved providers"):
        PlannedAnalysis(lane=AnalysisLane.MARKET, providers=["arbitrary-tool"], reason="no")


def test_fundamental_agent_preserves_numeric_source_metrics() -> None:
    run_id, instrument_id, evidence_id = uuid4(), uuid4(), uuid4()
    metrics = [
        MetricObservation(
            id=uuid4(),
            run_id=run_id,
            instrument_id=instrument_id,
            metric_name="revenue_growth",
            value=0.39,
            unit="percent",
            observed_at=datetime(2026, 9, 1, tzinfo=UTC),
            provider="sec",
            evidence_id=evidence_id,
        ),
        MetricObservation(
            id=uuid4(),
            run_id=run_id,
            instrument_id=instrument_id,
            metric_name="price_to_earnings",
            value=20.0,
            unit="multiple",
            observed_at=datetime(2026, 9, 1, tzinfo=UTC),
            provider="openbb",
            evidence_id=evidence_id,
        ),
    ]
    finding = FundamentalAnalystNode().analyze(run_id, metrics)
    assert verify_numeric_claims(finding, metrics)
    assert finding.numeric_claims[0].value == 0.39
    assert finding.numeric_claims[0].unit == "percent"


def test_event_agent_uses_distinct_evidence_and_never_uses_volume_as_strength() -> None:
    first, second = uuid4(), uuid4()
    findings = NewsEventAnalystNode().analyze(
        [
            EventEvidence(
                evidence_id=first,
                source_key="company-ir",
                category="guidance",
                excerpt="Raised outlook",
                direction=EventDirection.POSITIVE,
            ),
            EventEvidence(
                evidence_id=second,
                source_key="sec-8k",
                category="guidance",
                excerpt="Updated outlook",
                direction=EventDirection.POSITIVE,
            ),
        ]
    )
    assert findings[0].evidence_ids == [first, second]
    assert "Article count" in findings[0].limitations[0]
