"""Typed, provider-neutral records used throughout a research run."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


NonEmpty = Annotated[str, Field(min_length=1)]


class AssetType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    FUND = "fund"
    INDEX = "index"
    CRYPTO = "crypto"
    FX = "fx"
    COMMODITY = "commodity"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceKind(str, Enum):
    FILING = "filing"
    PRESS_RELEASE = "press_release"
    NEWS_ARTICLE = "news_article"
    MARKET_DATA = "market_data"
    ANALYST_REPORT = "analyst_report"
    TRANSCRIPT = "transcript"
    DATASET = "dataset"


class QualitySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DomainModel(BaseModel):
    """Reject accidental/coerced data at persistence boundaries."""

    model_config = ConfigDict(extra="forbid", strict=True)


class Instrument(DomainModel):
    id: UUID
    symbol: NonEmpty
    asset_type: AssetType
    name: str | None = None
    exchange: str | None = None
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class ResearchRun(DomainModel):
    id: UUID
    instrument_id: UUID
    status: RunStatus = RunStatus.PENDING
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    provider_config_version: NonEmpty
    scope: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_timeline(self) -> "ResearchRun":
        _require_timezone(self.requested_at, "requested_at")
        for name, timestamp in (
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
        ):
            if timestamp is not None:
                _require_timezone(timestamp, name)
        if self.started_at and self.started_at < self.requested_at:
            raise ValueError("started_at cannot be before requested_at")
        if self.completed_at and self.started_at and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be before started_at")
        return self


class SourceDocument(DomainModel):
    id: UUID
    provider: NonEmpty
    canonical_url: AnyUrl
    title: NonEmpty
    published_at: datetime | None = None
    retrieved_at: datetime
    content_hash: NonEmpty
    artifact_id: str | None = None
    terms_classification: NonEmpty

    @model_validator(mode="after")
    def validate_timestamps(self) -> "SourceDocument":
        _require_timezone(self.retrieved_at, "retrieved_at")
        if self.published_at is not None:
            _require_timezone(self.published_at, "published_at")
        return self


class Evidence(DomainModel):
    id: UUID
    run_id: UUID
    source_document_id: UUID | None = None
    provider: NonEmpty
    kind: EvidenceKind
    retrieved_at: datetime
    locator: NonEmpty
    content_hash: NonEmpty
    excerpt: str | None = None
    raw_artifact_id: str | None = None

    @model_validator(mode="after")
    def validate_retrieval_time(self) -> "Evidence":
        _require_timezone(self.retrieved_at, "retrieved_at")
        return self


class MetricObservation(DomainModel):
    id: UUID
    run_id: UUID
    instrument_id: UUID
    metric_name: NonEmpty
    value: float
    unit: NonEmpty
    observed_at: datetime
    provider: NonEmpty
    evidence_id: UUID

    @model_validator(mode="after")
    def validate_observed_at(self) -> "MetricObservation":
        _require_timezone(self.observed_at, "observed_at")
        return self


class Finding(DomainModel):
    id: UUID
    run_id: UUID
    summary: NonEmpty
    evidence_ids: list[UUID] = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


class Claim(DomainModel):
    id: UUID
    run_id: UUID
    statement: NonEmpty
    evidence_ids: list[UUID] = Field(min_length=1)
    claim_type: NonEmpty
    is_model_inference: bool = False


class Forecast(DomainModel):
    id: UUID
    run_id: UUID
    instrument_id: UUID
    horizon: NonEmpty
    generated_at: datetime
    model_name: NonEmpty
    direction: NonEmpty
    confidence: float | None = Field(default=None, ge=0, le=1)
    validation_reference: str | None = None
    evidence_ids: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_forecast(self) -> "Forecast":
        _require_timezone(self.generated_at, "generated_at")
        if self.confidence is not None and not self.validation_reference:
            raise ValueError(
                "validation_reference is required when forecast confidence is provided"
            )
        return self


class DataQualityIssue(DomainModel):
    id: UUID
    run_id: UUID
    severity: QualitySeverity
    code: NonEmpty
    message: NonEmpty
    evidence_id: UUID | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_created_at(self) -> "DataQualityIssue":
        _require_timezone(self.created_at, "created_at")
        return self


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
