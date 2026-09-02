"""Evidence-bound interpretation of financial quality, valuation, earnings, and peers."""

from __future__ import annotations

from uuid import UUID

from financial_ai.agents.models import AgentFinding, NumericClaim
from financial_ai.domain.models import MetricObservation


FUNDAMENTAL_METRICS = frozenset(
    {
        "revenue_growth",
        "eps_growth",
        "free_cash_flow_growth",
        "gross_margin",
        "operating_margin",
        "roe",
        "roic",
        "debt_to_equity",
        "price_to_earnings",
        "price_to_sales",
        "ev_to_ebitda",
        "earnings_surprise",
        "revenue_surprise",
        "peer_percentile",
    }
)


class FundamentalAnalystNode:
    """Turns supplied normalized metrics into a cited finding without changing values."""

    def analyze(self, run_id: UUID, metrics: list[MetricObservation]) -> AgentFinding:
        relevant = [metric for metric in metrics if metric.metric_name in FUNDAMENTAL_METRICS]
        if not relevant:
            raise ValueError("fundamental analysis requires supported source metrics")
        if any(metric.run_id != run_id for metric in relevant):
            raise ValueError("all metrics must belong to the research run")
        claims = [
            NumericClaim(
                metric_name=metric.metric_name,
                value=metric.value,
                unit=metric.unit,
                evidence_id=metric.evidence_id,
            )
            for metric in relevant
        ]
        limitations = [
            f"{name} is unavailable."
            for name in (
                "revenue_growth",
                "free_cash_flow_growth",
                "price_to_earnings",
                "peer_percentile",
            )
            if name not in {metric.metric_name for metric in relevant}
        ]
        return AgentFinding(
            summary=(
                "Financial quality, valuation, earnings, and peer observations are reported from "
                "normalized source metrics; they are research evidence, not an investment recommendation."
            ),
            evidence_ids=list(dict.fromkeys(claim.evidence_id for claim in claims)),
            limitations=limitations,
            numeric_claims=claims,
        )


def verify_numeric_claims(finding: AgentFinding, metrics: list[MetricObservation]) -> bool:
    """Ensure every displayed numeric claim exactly matches a supplied source metric."""

    source = {(item.metric_name, item.evidence_id): (item.value, item.unit) for item in metrics}
    return all(
        source.get((claim.metric_name, claim.evidence_id)) == (claim.value, claim.unit)
        for claim in finding.numeric_claims
    )
