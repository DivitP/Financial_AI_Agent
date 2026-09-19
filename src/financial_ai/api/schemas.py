"""Public request and response schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from financial_ai.domain.forecast import KronosResponse, KronosForecastData


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateResearchJobRequest(ApiSchema):
    ticker: str = Field(min_length=1, max_length=15)
    investment_horizon: Literal["short", "medium", "long"] | None = None
    risk_lens: Literal["conservative", "balanced", "growth"] | None = None
    thesis: str | None = Field(default=None, max_length=500)
    include_kronos: bool = False
    forecast_horizon: int = Field(default=5, ge=1, le=128)

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
    asset_type: Literal["equity", "etf"]
    correlation_id: str


class ResearchSnapshotResponse(ApiSchema):
    lane: str
    status: Literal["completed", "failed"]
    payload: dict[str, object] | None = None
    error_message: str | None = None


class ReportResponse(ApiSchema):
    id: UUID
    run_id: UUID
    version: int
    as_of: datetime
    model_configuration: dict[str, str]
    decision_brief: list[str]
    sections: list[dict[str, object]]
    evidence_links: dict[str, str]


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


class HistoryUpdate(ApiSchema):
    name: str | None = Field(default=None, max_length=80)
    archived: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        return value.strip() or None if value is not None else None


class HistoryItem(BaseModel):
    id: str
    ticker: str
    status: str
    requested_at: str
    name: str | None
    archived: bool
    report_count: int
