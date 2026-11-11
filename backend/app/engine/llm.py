"""The model provider boundary.

The engine speaks only the neutral types in this module. Each provider client translates them to
its own wire format, so the loop can be tested with a scripted fake and a provider can be added
without touching the engine.

Conversation messages are plain JSON-serializable dicts (so a run can be checkpointed later):

    {"role": "user", "text": "..."}
    {"role": "assistant", "text": "...", "tool_calls": [{"id", "name", "args"}],
     "provider_state": ...}
    {"role": "tool", "results": [{"id", "name", "content": "...", "is_error": bool}]}

`provider_state` is whatever the provider returned for that turn, stored verbatim and sent back
verbatim. Some providers require this: Gemini 3 and newer reject a function-calling request with
a 400 if the "thought signatures" they issued are not returned exactly as received.
"""

import enum
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import get_settings
from app.models.enums import LLMProvider

Message = dict[str, Any]
ToolSpec = dict[str, Any]  # {"name": str, "description": str, "input_schema": JSON Schema}


class LLMError(Exception):
    """The provider could not answer. The message is safe to show to users."""


class FinishReason(enum.StrEnum):
    STOP = "stop"  # the model finished its answer
    TOOL_CALLS = "tool_calls"  # the model wants tools run before it continues
    MAX_TOKENS = "max_tokens"  # the reply was cut off by the output limit
    REFUSED = "refused"  # blocked by the provider's safety systems


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str  # the name the model saw (see ToolDefinition.llm_name)
    args: Any


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    finish: FinishReason
    input_tokens: int
    output_tokens: int  # includes hidden "thinking" tokens, which providers bill as output
    provider_state: Any = None


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_output_tokens: int | None,
    ) -> LLMResponse: ...


def user_message(text: str) -> Message:
    return {"role": "user", "text": text}


def assistant_message(response: LLMResponse) -> Message:
    return {
        "role": "assistant",
        "text": response.text,
        "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in response.tool_calls],
        "provider_state": response.provider_state,
    }


def tool_message(results: list[dict[str, Any]]) -> Message:
    return {"role": "tool", "results": results}


def get_llm_client(provider: LLMProvider) -> LLMClient:
    """Build the client for a provider, or raise LLMError if it cannot be used."""
    settings = get_settings()
    if provider.value not in settings.enabled_llm_providers:
        raise LLMError(f"The {provider.value} provider is not enabled on this platform.")
    if provider is LLMProvider.GEMINI:
        from app.engine.gemini import GeminiClient

        if settings.gemini_api_key is None:
            raise LLMError("The Gemini provider is not configured (GEMINI_API_KEY is not set).")
        return GeminiClient(
            api_key=settings.gemini_api_key.get_secret_value(),
            base_url=settings.gemini_base_url,
            timeout=settings.llm_timeout_seconds,
        )
    raise LLMError(f"The {provider.value} provider is not implemented yet.")
