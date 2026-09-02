from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from financial_ai.llm import ChatMessage, ChatResponse, create_chat_provider
from financial_ai.prompts import MalformedModelResponse, PromptRegistry, StructuredPromptExecutor
from settings import Settings


class ScriptedProvider:
    provider = "fixture"
    model = "fixture-model-v1"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[ChatMessage], int]] = []

    async def complete(self, messages: list[ChatMessage], *, token_budget: int) -> ChatResponse:
        self.calls.append((messages, token_budget))
        return ChatResponse(content=self.responses.pop(0), provider=self.provider, model=self.model)


def test_llm_is_optional_for_offline_data_collection() -> None:
    assert create_chat_provider(Settings(_env_file=None)) is None  # type: ignore[call-arg]


def test_chat_provider_configuration_rejects_two_selected_providers() -> None:
    with pytest.raises(ValidationError, match="Enable only one chat provider"):
        Settings(  # type: ignore[call-arg]
            ENABLE_GROQ=True,
            GROQ_API_KEY="test-key",
            ENABLE_LOCAL_LLM=True,
            _env_file=None,
        )


@pytest.mark.anyio
async def test_prompt_response_retries_then_tracks_prompt_and_model_versions() -> None:
    fixture = Path(__file__).parent / "fixtures" / "prompts" / "research_brief_valid.json"
    provider = ScriptedProvider(["not json", fixture.read_text(encoding="utf-8")])

    result = await StructuredPromptExecutor(provider).execute(
        "research_brief", {"evidence": "evidence-annual-report: Revenue increased."}
    )

    assert result.prompt_version == "1.0.0"
    assert result.provider == "fixture"
    assert result.model == "fixture-model-v1"
    assert result.output.summary.startswith("Revenue grew")
    assert len(provider.calls) == 2
    assert provider.calls[0][1] == 400


@pytest.mark.anyio
async def test_prompt_response_is_rejected_after_bounded_retries() -> None:
    provider = ScriptedProvider(["{}", "still not json"])

    with pytest.raises(MalformedModelResponse, match="invalid research_brief output"):
        await StructuredPromptExecutor(provider).execute(
            "research_brief", {"evidence": "evidence-annual-report"}
        )
