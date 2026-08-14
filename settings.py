"""Typed runtime settings for the legacy application and its replacement."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and an optional `.env` file.

    Provider credentials are optional by default so local development and the offline
    test suite work without secrets. Enabling a provider without its credential fails
    fast with an actionable configuration error.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("FINANCIAL_AI_APP_ENVIRONMENT", "APP_ENVIRONMENT"),
    )
    host: str = Field(default="127.0.0.1", validation_alias="FINANCIAL_AI_HOST")
    port: int = Field(default=8501, ge=1, le=65535, validation_alias="PORT")
    debug: bool = Field(default=False, validation_alias="FINANCIAL_AI_DEBUG")

    persist_dir: Path = Field(
        default=Path("data/runtime"),
        validation_alias=AliasChoices("FINANCIAL_AI_PERSIST_DIR", "PERSIST_DIR"),
    )
    database_path: Path = Field(
        default=Path("data/runtime/financial_ai.db"),
        validation_alias="FINANCIAL_AI_DATABASE_PATH",
    )
    cache_ttl_seconds: int = Field(
        default=900, ge=0, le=86_400, validation_alias="CACHE_TTL_SECONDS"
    )
    request_timeout_seconds: float = Field(
        default=15.0, gt=0, le=120, validation_alias="REQUEST_TIMEOUT_SECONDS"
    )
    provider_rate_limit_per_minute: int = Field(
        default=30, ge=1, le=10_000, validation_alias="PROVIDER_RATE_LIMIT_PER_MINUTE"
    )

    enable_groq: bool = Field(default=False, validation_alias="ENABLE_GROQ")
    enable_fmp: bool = Field(default=False, validation_alias="ENABLE_FMP")
    enable_kronos: bool = Field(default=False, validation_alias="ENABLE_KRONOS")
    enable_local_llm: bool = Field(default=False, validation_alias="ENABLE_LOCAL_LLM")

    groq_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GROQ_API_KEY", "FINANCIAL_AI_GROQ_API_KEY"),
        repr=False,
    )
    fmp_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FMP_API_KEY", "FINANCIAL_AI_FMP_API_KEY"),
        repr=False,
    )
    groq_model: str = Field(default="llama-3.3-70b-versatile", validation_alias="GROQ_MODEL")
    local_llm_model: str = Field(default="qwen3:8b", validation_alias="LOCAL_LLM_MODEL")
    kronos_model: str = Field(default="NeoQuasar/Kronos-small", validation_alias="KRONOS_MODEL")

    @model_validator(mode="after")
    def validate_enabled_providers(self) -> "Settings":
        if self.enable_groq and self.groq_api_key is None:
            raise ValueError("ENABLE_GROQ=true requires GROQ_API_KEY.")
        if self.enable_fmp and self.fmp_api_key is None:
            raise ValueError("ENABLE_FMP=true requires FMP_API_KEY.")
        if self.app_environment == "production" and self.debug:
            raise ValueError("FINANCIAL_AI_DEBUG must be false in production.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for application startup."""

    return Settings()
