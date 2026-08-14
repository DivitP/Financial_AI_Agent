"""Sanitized fixture loader and reusable provider-result conformance assertions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from financial_ai.providers.contracts import ProviderResult


FixtureModel = TypeVar("FixtureModel", bound=BaseModel)


def load_fixture(path: Path, model: type[FixtureModel]) -> FixtureModel:
    """Load a checked-in sanitized fixture through the same schema used in adapters."""

    content = path.read_text(encoding="utf-8")
    if any(token in content.lower() for token in ("api_key", "authorization", "bearer ")):
        raise ValueError("provider fixture appears to contain a credential")
    return model.model_validate_json(content)


def assert_provider_conformance(result: ProviderResult[Any], expected_provider: str) -> None:
    assert result.provider == expected_provider
    assert (result.data is None) != (result.error is None)
    if result.data is not None:
        assert result.provenance
        for source in result.provenance:
            assert source.provider == expected_provider
            assert source.source_url.startswith(("https://", "http://"))
            assert source.retrieved_at.tzinfo is not None
    if result.error is not None:
        assert result.error.provider == expected_provider
