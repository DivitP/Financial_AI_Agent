"""Model-neutral interfaces for optional language-model features."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: str
    provider: str
    model: str


class ChatProvider(Protocol):
    """A provider that can complete a short, bounded chat exchange."""

    provider: str
    model: str

    async def complete(self, messages: list[ChatMessage], *, token_budget: int) -> ChatResponse: ...
