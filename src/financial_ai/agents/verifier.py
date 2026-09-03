"""Deterministic claim checks that block unsupported research-report content."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from pydantic import Field, model_validator

from financial_ai.agents.models import AgentModel, NumericClaim
from financial_ai.domain.models import MetricObservation


class ArithmeticOperation(str, Enum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"


class ArithmeticAssertion(AgentModel):
    left: float
    right: float
    operation: ArithmeticOperation
    result: float

    def is_correct(self) -> bool:
        expected = {
            ArithmeticOperation.ADD: self.left + self.right,
            ArithmeticOperation.SUBTRACT: self.left - self.right,
            ArithmeticOperation.MULTIPLY: self.left * self.right,
            ArithmeticOperation.DIVIDE: self.left / self.right if self.right else None,
        }[self.operation]
        return expected is not None and abs(expected - self.result) < 1e-9


class VerifiableClaim(AgentModel):
    statement: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(min_length=1)
    observed_at: datetime
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    arithmetic: ArithmeticAssertion | None = None
    certainty: float | None = Field(default=None, ge=0, le=1)
    out_of_sample_validation: str | None = None

    @model_validator(mode="after")
    def certainty_requires_validation(self) -> "VerifiableClaim":
        if self.certainty is not None and not self.out_of_sample_validation:
            raise ValueError("claim certainty requires out-of-sample validation")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone offset")
        return self


class BlockedClaim(AgentModel):
    statement: str
    reasons: list[str] = Field(min_length=1)


class VerificationResult(AgentModel):
    approved: list[VerifiableClaim]
    blocked: list[BlockedClaim]


class ClaimContradictionVerifier:
    """Approves only cited, current, unit-matched, non-contradictory claims."""

    def verify(
        self,
        claims: list[VerifiableClaim],
        metrics: list[MetricObservation],
        *,
        as_of: datetime,
        max_age: timedelta = timedelta(days=30),
    ) -> VerificationResult:
        source_by_key = {(item.metric_name, item.evidence_id): item for item in metrics}
        evidence_ids = {item.evidence_id for item in metrics}
        conflicting = {
            name
            for name in {item.metric_name for item in metrics}
            if len({item.value for item in metrics if item.metric_name == name}) > 1
        }
        approved: list[VerifiableClaim] = []
        blocked: list[BlockedClaim] = []
        for claim in claims:
            reasons: list[str] = []
            if not set(claim.evidence_ids).issubset(evidence_ids):
                reasons.append("missing citation")
            if as_of - claim.observed_at > max_age:
                reasons.append("stale information")
            if claim.arithmetic and not claim.arithmetic.is_correct():
                reasons.append("arithmetic mismatch")
            for numeric in claim.numeric_claims:
                source = source_by_key.get((numeric.metric_name, numeric.evidence_id))
                if source is None:
                    reasons.append(f"unsupported metric {numeric.metric_name}")
                elif (source.value, source.unit) != (numeric.value, numeric.unit):
                    reasons.append(f"unit or value mismatch for {numeric.metric_name}")
                elif as_of - source.observed_at > max_age:
                    reasons.append(f"stale source metric {numeric.metric_name}")
                if numeric.metric_name in conflicting:
                    reasons.append(f"contradictory source values for {numeric.metric_name}")
            if reasons:
                blocked.append(
                    BlockedClaim(statement=claim.statement, reasons=list(dict.fromkeys(reasons)))
                )
            else:
                approved.append(claim)
        return VerificationResult(approved=approved, blocked=blocked)
