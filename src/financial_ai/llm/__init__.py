"""Optional LLM capabilities. Core research collection does not depend on this package."""

from financial_ai.llm.contracts import ChatMessage, ChatProvider, ChatResponse
from financial_ai.llm.providers import (
    GroqChatProvider,
    LLMConfigurationError,
    OllamaChatProvider,
    create_chat_provider,
    validate_chat_configuration,
)

__all__ = [
    "ChatMessage",
    "ChatProvider",
    "ChatResponse",
    "GroqChatProvider",
    "LLMConfigurationError",
    "OllamaChatProvider",
    "create_chat_provider",
    "validate_chat_configuration",
]
