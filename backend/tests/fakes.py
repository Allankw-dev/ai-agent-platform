"""A scripted stand-in for an LLM provider, so the engine can be tested with no network."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.engine.llm import FinishReason, LLMResponse, Message, ToolCall, ToolSpec

Step = LLMResponse | Exception | Callable[[], Awaitable[LLMResponse]]


def reply(text: str, *, tokens_in: int = 10, tokens_out: int = 5) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=[],
        finish=FinishReason.STOP,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        provider_state=[{"text": text}],
    )


def call_tools(
    *calls: tuple[str, Any], text: str = "", tokens_in: int = 10, tokens_out: int = 5
) -> LLMResponse:
    """A reply asking for tools: each call is (model-facing tool name, arguments)."""
    tool_calls = [
        ToolCall(id=f"call_{i}", name=name, args=args) for i, (name, args) in enumerate(calls)
    ]
    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        finish=FinishReason.TOOL_CALLS,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        provider_state=[{"functionCall": {"name": c.name, "args": c.args}} for c in tool_calls],
    )


def with_finish(response: LLMResponse, finish: FinishReason) -> LLMResponse:
    return LLMResponse(
        text=response.text,
        tool_calls=response.tool_calls,
        finish=finish,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        provider_state=response.provider_state,
    )


class ScriptedLLM:
    """Plays back a fixed script and records every request it receives."""

    def __init__(self, *steps: Step) -> None:
        self._steps = list(steps)
        self.requests: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_output_tokens: int | None,
    ) -> LLMResponse:
        self.requests.append(
            {
                "model": model,
                "system": system,
                "messages": list(messages),
                "tools": tools,
                "max_output_tokens": max_output_tokens,
            }
        )
        if not self._steps:
            raise AssertionError("the model was called more times than the script allows")
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, LLMResponse):
            return step
        return await step()

    @property
    def calls(self) -> int:
        return len(self.requests)
