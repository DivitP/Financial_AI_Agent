"""Provider-independent failure categories suitable for retries and UI coverage gaps."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ProviderErrorCategory(str, Enum):
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TERMS_RESTRICTED = "terms_restricted"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    MALFORMED_RESPONSE = "malformed_response"


class ProviderError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str
    category: ProviderErrorCategory
    message: str
    retryable: bool = False
    retry_after_seconds: int | None = None
