from __future__ import annotations

import pytest
from pydantic import ValidationError

from settings import Settings


def test_defaults_allow_offline_development() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.enable_groq is False
    assert settings.enable_fmp is False
    assert settings.persist_dir.as_posix() == "data/runtime"


def test_enabled_groq_requires_a_key() -> None:
    with pytest.raises(ValidationError, match="ENABLE_GROQ=true requires GROQ_API_KEY"):
        Settings(ENABLE_GROQ=True, _env_file=None)  # type: ignore[call-arg]


def test_enabled_fmp_requires_a_key() -> None:
    with pytest.raises(ValidationError, match="ENABLE_FMP=true requires FMP_API_KEY"):
        Settings(ENABLE_FMP=True, _env_file=None)  # type: ignore[call-arg]


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="must be false in production"):
        Settings(  # type: ignore[call-arg]
            APP_ENVIRONMENT="production", FINANCIAL_AI_DEBUG=True, _env_file=None
        )
