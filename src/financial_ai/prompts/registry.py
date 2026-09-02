"""Versioned prompt definitions and safe structured-output execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from financial_ai.llm.contracts import ChatMessage, ChatProvider


class PromptDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    output_schema: str = Field(min_length=1)
    token_budget: int = Field(ge=1, le=8_192)
    system: str = Field(min_length=1)
    user_template: str = Field(min_length=1)


class ResearchBrief(BaseModel):
    """A deliberately small, evidence-linked example structured response."""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {"research_brief": ResearchBrief}
T = TypeVar("T", bound=BaseModel)


class PromptRegistry:
    """Loads immutable, reviewable JSON prompts stored beside application code."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or Path(__file__).with_name("definitions")

    def get(self, prompt_id: str) -> PromptDefinition:
        matches = sorted(self.directory.glob(f"{prompt_id}.v*.json"))
        if not matches:
            raise KeyError(f"Prompt '{prompt_id}' is not registered.")
        definition = PromptDefinition.model_validate_json(matches[-1].read_text(encoding="utf-8"))
        if definition.output_schema not in OUTPUT_SCHEMAS:
            raise ValueError(f"Prompt '{prompt_id}' declares an unknown output schema.")
        return definition

    def schema_for(self, definition: PromptDefinition) -> type[BaseModel]:
        return OUTPUT_SCHEMAS[definition.output_schema]

    def render(self, definition: PromptDefinition, values: Mapping[str, str]) -> list[ChatMessage]:
        try:
            user_content = definition.user_template.format_map(values)
        except KeyError as error:
            raise ValueError(
                f"Prompt '{definition.id}' is missing variable {error.args[0]!r}."
            ) from error
        return [
            ChatMessage(role="system", content=definition.system),
            ChatMessage(role="user", content=user_content),
        ]


class StructuredModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    prompt_id: str
    prompt_version: str
    provider: str
    model: str
    output: BaseModel


class MalformedModelResponse(ValueError):
    """A response that cannot meet a prompt's declared Pydantic schema."""


class StructuredPromptExecutor:
    """Executes prompts with bounded retries and rejects invalid model output."""

    def __init__(self, provider: ChatProvider, registry: PromptRegistry | None = None) -> None:
        self.provider = provider
        self.registry = registry or PromptRegistry()

    async def execute(
        self, prompt_id: str, values: Mapping[str, str], *, retries: int = 1
    ) -> StructuredModelResponse:
        definition = self.registry.get(prompt_id)
        messages = self.registry.render(definition, values)
        schema = self.registry.schema_for(definition)
        for attempt in range(retries + 1):
            response = await self.provider.complete(messages, token_budget=definition.token_budget)
            try:
                output = schema.model_validate_json(response.content)
            except (ValidationError, json.JSONDecodeError) as error:
                if attempt == retries:
                    raise MalformedModelResponse(
                        f"Prompt '{definition.id}' returned invalid {definition.output_schema} output."
                    ) from error
                messages = [
                    *messages,
                    ChatMessage(
                        role="user",
                        content="Return only valid JSON that matches the required output schema.",
                    ),
                ]
                continue
            return StructuredModelResponse(
                prompt_id=definition.id,
                prompt_version=definition.version,
                provider=response.provider,
                model=response.model,
                output=output,
            )
        raise AssertionError("unreachable")
