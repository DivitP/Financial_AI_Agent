"""Typed, evidence-first outputs shared by research analyst nodes."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NumericClaim(AgentModel):
    metric_name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    evidence_id: UUID


class AgentFinding(AgentModel):
    summary: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
