"""Technical interpretation with explicit validation requirements for forecasts."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from financial_ai.agents.models import AgentFinding, AgentModel, NumericClaim


class TechnicalObservation(AgentModel):
    name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    evidence_id: UUID


class ValidatedForecastOutput(AgentModel):
    model_name: str = Field(min_length=1)
    horizon: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    out_of_sample_validation: str | None = None

    @model_validator(mode="after")
    def confidence_requires_out_of_sample_validation(self) -> "ValidatedForecastOutput":
        if self.confidence is not None and not self.out_of_sample_validation:
            raise ValueError("forecast confidence requires out-of-sample validation")
        return self


class TechnicalFinding(AgentFinding):
    forecast: ValidatedForecastOutput | None = None


class TechnicalQuantAnalystNode:
    """Describes market conditions without emitting BUY/SELL instructions."""

    def analyze(
        self,
        *,
        regime: str,
        trend: str,
        momentum: str,
        observations: list[TechnicalObservation],
        forecast: ValidatedForecastOutput | None = None,
    ) -> TechnicalFinding:
        if not observations:
            raise ValueError("technical analysis requires cited observations")
        claims = [
            NumericClaim(
                metric_name=item.name,
                value=item.value,
                unit=item.unit,
                evidence_id=item.evidence_id,
            )
            for item in observations
        ]
        return TechnicalFinding(
            summary=(
                f"The observed market regime is {regime}, with {trend} trend and {momentum} momentum. "
                "These indicators describe conditions and are not a BUY or SELL instruction."
            ),
            evidence_ids=list(dict.fromkeys(item.evidence_id for item in observations)),
            limitations=[
                "Technical indicators and liquidity measures may be delayed or incomplete.",
                "Forecast confidence is omitted unless out-of-sample validation is documented.",
            ],
            numeric_claims=claims,
            forecast=forecast,
        )
