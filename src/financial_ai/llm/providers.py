"""Optional Groq and Ollama-compatible chat adapters."""

from __future__ import annotations

from typing import Any

from settings import Settings

from financial_ai.llm.contracts import ChatMessage, ChatProvider, ChatResponse


class LLMConfigurationError(ValueError):
    """Raised for a selected LLM provider that cannot be safely configured."""


class LLMDisabledError(RuntimeError):
    """Raised only when an optional LLM feature is invoked while disabled."""


def validate_chat_configuration(settings: Settings) -> None:
    """Validate selection locally; never contact a provider during application startup."""

    if settings.enable_groq and not settings.groq_api_key:
        raise LLMConfigurationError("ENABLE_GROQ=true requires GROQ_API_KEY.")
    if settings.enable_groq and settings.enable_local_llm:
        raise LLMConfigurationError("Select one chat provider, not both Groq and local Ollama.")
    if settings.enable_local_llm and not settings.local_llm_base_url.startswith(
        ("http://", "https://")
    ):
        raise LLMConfigurationError("LOCAL_LLM_BASE_URL must be an http(s) URL.")


def create_chat_provider(settings: Settings) -> ChatProvider | None:
    """Return the selected provider, or ``None`` when all LLM features are disabled."""

    validate_chat_configuration(settings)
    if settings.enable_groq:
        api_key = settings.groq_api_key
        assert api_key is not None
        return GroqChatProvider(settings.groq_model, api_key.get_secret_value())
    if settings.enable_local_llm:
        return OllamaChatProvider(settings.local_llm_model, settings.local_llm_base_url)
    return None


class GroqChatProvider:
    provider = "groq"

    def __init__(self, model: str, api_key: str, client: Any | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client

    def _chat_client(self) -> Any:
        if self._client is None:
            from langchain_groq import ChatGroq

            self._client = ChatGroq(model=self.model, api_key=self._api_key, temperature=0)
        return self._client

    async def complete(self, messages: list[ChatMessage], *, token_budget: int) -> ChatResponse:
        response = await self._chat_client().ainvoke(
            [(message.role, message.content) for message in messages],
            max_tokens=token_budget,
        )
        return ChatResponse(content=_content(response), provider=self.provider, model=self.model)


class OllamaChatProvider:
    provider = "ollama"

    def __init__(self, model: str, base_url: str, client: Any | None = None) -> None:
        self.model = model
        self._base_url = base_url
        self._client = client

    def _chat_client(self) -> Any:
        if self._client is None:
            try:
                from langchain_ollama import ChatOllama
            except ImportError as error:
                raise LLMConfigurationError(
                    "Local LLM support requires `uv sync --extra local-llm`."
                ) from error
            self._client = ChatOllama(model=self.model, base_url=self._base_url, temperature=0)
        return self._client

    async def complete(self, messages: list[ChatMessage], *, token_budget: int) -> ChatResponse:
        response = await self._chat_client().ainvoke(
            [(message.role, message.content) for message in messages],
            num_predict=token_budget,
        )
        return ChatResponse(content=_content(response), provider=self.provider, model=self.model)


def _content(response: Any) -> str:
    content = getattr(response, "content", response)
    if not isinstance(content, str):
        raise LLMDisabledError("The configured chat provider returned non-text content.")
    return content
