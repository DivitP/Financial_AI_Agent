from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from financial_ai.agents.models import AgentFinding, NumericClaim
from financial_ai.agents.risk import (
    RiskAnalystNode,
    RiskCategory,
    RiskSignal,
    compose_final_findings,
)
from financial_ai.agents.technical import (
    TechnicalObservation,
    TechnicalQuantAnalystNode,
    ValidatedForecastOutput,
)
from financial_ai.agents.verifier import ClaimContradictionVerifier, VerifiableClaim
from financial_ai.domain.models import MetricObservation


NOW = datetime(2026, 9, 3, tzinfo=UTC)


def _metric(value: float = 0.2) -> MetricObservation:
    return MetricObservation(
        id=uuid4(),
        run_id=uuid4(),
        instrument_id=uuid4(),
        metric_name="volatility",
        value=value,
        unit="percent",
        observed_at=NOW,
        provider="openbb",
        evidence_id=uuid4(),
    )


def test_technical_node_requires_out_of_sample_validation_for_confidence() -> None:
    with pytest.raises(ValueError, match="out-of-sample"):
        ValidatedForecastOutput(model_name="test", horizon="30d", direction="up", confidence=0.9)
    metric = _metric()
    finding = TechnicalQuantAnalystNode().analyze(
        regime="trending",
        trend="uptrend",
        momentum="positive",
        observations=[
            TechnicalObservation(
                name="volatility", value=0.2, unit="percent", evidence_id=metric.evidence_id
            )
        ],
    )
    assert "BUY or SELL" in finding.summary
    assert finding.forecast is None


def test_adverse_risk_evidence_is_preserved_by_final_composer() -> None:
    evidence = uuid4()
    assessment = RiskAnalystNode().analyze(
        [
            RiskSignal(
                category=RiskCategory.CONCENTRATION,
                description="Top customer concentration",
                evidence_ids=[evidence],
            )
        ]
    )
    composed = compose_final_findings(
        [AgentFinding(summary="Other finding", evidence_ids=[uuid4()])], assessment
    )
    assert composed[-1].evidence_ids == [evidence]


def test_verifier_blocks_hallucinated_and_stale_or_contradictory_claims() -> None:
    metric = _metric()
    valid = VerifiableClaim(
        statement="Observed volatility was 20%.",
        evidence_ids=[metric.evidence_id],
        observed_at=NOW,
        numeric_claims=[
            NumericClaim(
                metric_name="volatility",
                value=0.2,
                unit="percent",
                evidence_id=metric.evidence_id,
            )
        ],
    )
    hallucinated = VerifiableClaim(
        statement="Invented claim.", evidence_ids=[uuid4()], observed_at=NOW
    )
    stale = VerifiableClaim(
        statement="Old claim.",
        evidence_ids=[metric.evidence_id],
        observed_at=NOW - timedelta(days=31),
    )
    result = ClaimContradictionVerifier().verify([valid, hallucinated, stale], [metric], as_of=NOW)
    assert result.approved == [valid]
    assert {item.statement for item in result.blocked} == {"Invented claim.", "Old claim."}
