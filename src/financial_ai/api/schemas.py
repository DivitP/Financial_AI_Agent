"""Public request and response schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateResearchJobRequest(ApiSchema):
    ticker: str = Field(min_length=1, max_length=15)
    investment_horizon: Literal["short", "medium", "long"] | None = None
    risk_lens: Literal["conservative", "balanced", "growth"] | None = None
    thesis: str | None = Field(default=None, max_length=500)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,14}", normalized):
            raise ValueError("ticker must contain only letters, numbers, '.', '_' or '-'")
        return normalized

    @field_validator("thesis")
    @classmethod
    def normalize_thesis(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


class JobResponse(ApiSchema):
    id: UUID
    run_id: UUID
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    correlation_id: str


class ResearchRunResponse(ApiSchema):
    id: UUID
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    ticker: str
    correlation_id: str


class ResearchSnapshotResponse(ApiSchema):
    lane: str
    status: Literal["completed", "failed"]
    payload: dict[str, object] | None = None
    error_message: str | None = None


class HealthResponse(ApiSchema):
    status: Literal["ok"]


class VersionResponse(ApiSchema):
    version: str
    api_version: str


class JobEventResponse(ApiSchema):
    id: int
    job_id: UUID
    kind: str
    payload: dict[str, object]
    created_at: datetime
