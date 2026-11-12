"""Google Gemini over its REST API (generateContent), using httpx.

No SDK is needed: the engine uses one endpoint and a handful of fields. Notes that matter:

- The assistant's raw `parts` are stored as `provider_state` and replayed unchanged, so thought
  signatures survive between tool-calling steps (Gemini 3+ returns a 400 without them).
- Tool schemas are reduced to the OpenAPI subset Gemini accepts. Dropped keywords such as
  `additionalProperties` are still enforced by the platform, which validates every tool call
  against the full schema before running it.
- Output tokens include "thinking" tokens (`thoughtsTokenCount`), which are billed as output.
- 429 and 5xx responses are retried briefly; the free tier has strict per-minute limits.
"""

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
import structlog

from app.engine.llm import (
    FinishReason,
    LLMError,
    LLMResponse,
    Message,
    ToolCall,
    ToolSpec,
)

log = structlog.get_logger()

RETRY_DELAYS = (2.0, 6.0)  # seconds between attempts for 429 / 5xx (so three attempts in all)
# A request that already made us wait this long before failing will not recover in a few seconds
# (an overloaded model can take close to a minute to say so), so it is not retried.
SLOW_FAILURE_SECONDS = 15.0

# The subset of JSON Schema that Gemini's function declarations understand.
_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "maxItems",
    "minItems",
    "properties",
    "required",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "title",
    "default",
    "items",
    "anyOf",
}
_SAFETY_REASONS = {
    "SAFETY",
    "RECITATION",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "LANGUAGE",
}


def to_gemini_schema(schema: Any) -> Any:
    """Reduce a JSON Schema to the subset Gemini accepts (and upper-case its type names)."""
    if isinstance(schema, list):
        return [to_gemini_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    converted: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            converted[key] = {name: to_gemini_schema(sub) for name, sub in value.items()}
        elif key == "type" and isinstance(value, str):
            converted[key] = value.upper()
        elif key in ("items", "anyOf"):
            converted[key] = to_gemini_schema(value)
        else:
            converted[key] = value
    return converted


def _function_response_parts(
    results: list[dict[str, Any]], calls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for position, result in enumerate(results):
        call = calls[position] if position < len(calls) else {}
        key = "error" if result.get("is_error") else "output"
        response: dict[str, Any] = {
            "name": call.get("name") or result["name"],
            "response": {key: result["content"]},
        }
        if call.get("id"):
            response["id"] = call["id"]
        parts.append({"functionResponse": response})
    return parts


def to_gemini_contents(messages: list[Message]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    last_calls: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "user":
            contents.append({"role": "user", "parts": [{"text": message["text"]}]})
        elif role == "assistant":
            parts = message.get("provider_state")
            if not isinstance(parts, list) or not parts:
                parts = []
                if message.get("text"):
                    parts.append({"text": message["text"]})
                for call in message.get("tool_calls", []):
                    parts.append({"functionCall": {"name": call["name"], "args": call["args"]}})
            contents.append({"role": "model", "parts": parts})
            last_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        elif role == "tool":
            contents.append(
                {"role": "user", "parts": _function_response_parts(message["results"], last_calls)}
            )
    return contents


def _error_for_status(status: int, model: str) -> LLMError:
    if status in (401, 403):
        return LLMError("The AI provider rejected the platform's API key.")
    if status == 404:
        return LLMError(f"The AI provider does not know the model {model!r}.")
    if status == 429:
        return LLMError(
            "The AI provider is rate limiting requests (free tiers have strict per-minute "
            "limits). Wait a minute and try again."
        )
    if status == 503:
        return LLMError(
            f"The model {model!r} is overloaded right now (HTTP 503). Try again in a few "
            "minutes or choose another model."
        )
    if status >= 500:
        return LLMError("The AI provider is temporarily unavailable. Try again soon.")
    return LLMError(f"The AI provider rejected the request (HTTP {status}).")


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retry_delays = retry_delays
        self._transport = transport
        self._clock = clock

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_output_tokens: int | None,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": to_gemini_contents(messages),
        }
        if max_output_tokens:
            body["generationConfig"] = {"maxOutputTokens": max_output_tokens}
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": to_gemini_schema(tool["input_schema"]),
                        }
                        for tool in tools
                    ]
                }
            ]
        data = await self._post(model, body)
        return self._parse(data)

    async def _post(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/models/{model}:generateContent"
        headers = {"x-goog-api-key": self._api_key, "content-type": "application/json"}
        attempts = len(self._retry_delays) + 1
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(attempts):
                started = self._clock()
                try:
                    response = await client.post(url, json=body, headers=headers)
                except httpx.ConnectTimeout as exc:
                    log.warning("llm.connect_timeout", model=model)
                    raise LLMError("The AI provider could not be reached.") from exc
                except httpx.TimeoutException as exc:
                    log.warning("llm.read_timeout", model=model, seconds=self._timeout)
                    raise LLMError(
                        f"The model {model!r} did not answer within {self._timeout:g} seconds; it "
                        "may be overloaded. Try again or choose another model."
                    ) from exc
                except httpx.HTTPError as exc:
                    log.warning("llm.connection_error", model=model, error=type(exc).__name__)
                    raise LLMError("The AI provider could not be reached.") from exc

                if response.status_code == 200:
                    payload = response.json()
                    return payload if isinstance(payload, dict) else {}
                retryable = response.status_code == 429 or response.status_code >= 500
                slow = self._clock() - started > SLOW_FAILURE_SECONDS
                if retryable and not slow and attempt < attempts - 1:
                    await asyncio.sleep(self._retry_delays[attempt])
                    continue
                log.warning("llm.status_error", status=response.status_code, model=model)
                raise _error_for_status(response.status_code, model)
        raise LLMError("The AI provider could not be reached.")  # pragma: no cover

    @staticmethod
    def _parse(data: dict[str, Any]) -> LLMResponse:
        usage = data.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0) + int(
            usage.get("thoughtsTokenCount") or 0
        )
        candidates = data.get("candidates") or []
        if not candidates:
            # Nothing was generated: the prompt itself was blocked.
            return LLMResponse(
                text="",
                tool_calls=[],
                finish=FinishReason.REFUSED,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for part in parts:
            if "functionCall" in part:
                call = part["functionCall"]
                calls.append(
                    ToolCall(
                        id=str(call.get("id") or f"call_{len(calls)}"),
                        name=str(call.get("name", "")),
                        args=call.get("args") or {},
                    )
                )
            elif isinstance(part.get("text"), str) and not part.get("thought"):
                text_parts.append(part["text"])

        reason = str(candidate.get("finishReason") or "STOP")
        if reason == "MAX_TOKENS":
            finish = FinishReason.MAX_TOKENS
        elif reason in _SAFETY_REASONS:
            finish = FinishReason.REFUSED
        elif reason in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            finish = FinishReason.TOOL_CALLS if calls else FinishReason.STOP
        else:
            # MALFORMED_FUNCTION_CALL, OTHER, ...: nothing usable came back.
            raise LLMError(f"The AI provider stopped unexpectedly ({reason}).")
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=calls,
            finish=finish,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_state=parts or None,
        )
