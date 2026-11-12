"""The Gemini client against a mocked HTTP transport. No network and no real key."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.engine.gemini import GeminiClient, to_gemini_contents, to_gemini_schema
from app.engine.llm import FinishReason, LLMError

SECRET = "AIza-super-secret-key"  # noqa: S105 (a fake value used to prove it never leaks)
TOOLS = [
    {
        "name": "utility_calculate",
        "description": "Evaluate arithmetic.",
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "maxLength": 200}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    }
]


def client(
    handler: Callable[[httpx.Request], httpx.Response], delays: tuple[float, ...] = ()
) -> GeminiClient:
    return GeminiClient(
        api_key=SECRET,
        base_url="https://gemini.test/v1beta/",
        timeout=5,
        retry_delays=delays,
        transport=httpx.MockTransport(handler),
    )


def answer(parts: list[Any], **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
    }
    body.update(extra)
    return body


async def complete(gemini: GeminiClient, messages: list[dict[str, Any]] | None = None) -> Any:
    return await gemini.complete(
        model="gemini-x",
        system="Be brief.",
        messages=messages or [{"role": "user", "text": "hi"}],
        tools=TOOLS,
        max_output_tokens=256,
    )


# ---------- the request ----------


async def test_request_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=answer([{"text": "hello"}]))

    await complete(client(handler))
    assert seen["url"] == "https://gemini.test/v1beta/models/gemini-x:generateContent"
    assert seen["key"] == SECRET
    body = seen["body"]
    assert body["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    assert body["generationConfig"] == {"maxOutputTokens": 256}
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "utility_calculate"
    assert declaration["parameters"]["type"] == "OBJECT"
    assert "additionalProperties" not in declaration["parameters"]
    assert declaration["parameters"]["properties"]["expression"]["type"] == "STRING"


async def test_the_api_key_is_sent_in_a_header_never_in_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert SECRET not in str(request.url)
        return httpx.Response(200, json=answer([{"text": "ok"}]))

    await complete(client(handler))


async def test_no_tools_and_no_token_cap_are_omitted() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=answer([{"text": "ok"}]))

    await client(handler).complete(
        model="m",
        system="s",
        messages=[{"role": "user", "text": "x"}],
        tools=[],
        max_output_tokens=None,
    )
    assert "tools" not in seen
    assert "generationConfig" not in seen


def test_schema_is_reduced_to_what_gemini_accepts() -> None:
    schema = {
        "type": "object",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "tags": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}},
            "n": {"type": "integer", "minimum": 1, "exclusiveMinimum": 0},
        },
        "required": ["tags"],
    }
    assert to_gemini_schema(schema) == {
        "type": "OBJECT",
        "properties": {
            "tags": {"type": "ARRAY", "items": {"type": "STRING", "enum": ["a", "b"]}},
            "n": {"type": "INTEGER", "minimum": 1},
        },
        "required": ["tags"],
    }


def test_a_property_called_like_a_keyword_survives() -> None:
    schema = {
        "type": "object",
        "properties": {"type": {"type": "string"}, "items": {"type": "string"}},
    }
    converted = to_gemini_schema(schema)
    assert set(converted["properties"]) == {"type", "items"}


# ---------- history: provider state is replayed untouched ----------


def test_assistant_turns_replay_the_providers_raw_parts_including_thought_signatures() -> None:
    raw = [
        {"functionCall": {"name": "t", "args": {"a": 1}, "id": "fc1"}, "thoughtSignature": "SIG"}
    ]
    contents = to_gemini_contents(
        [
            {"role": "user", "text": "go"},
            {
                "role": "assistant",
                "text": "",
                "tool_calls": [{"id": "fc1", "name": "t", "args": {"a": 1}}],
                "provider_state": raw,
            },
            {
                "role": "tool",
                "results": [{"id": "fc1", "name": "t", "content": "42", "is_error": False}],
            },
        ]
    )
    assert contents[1] == {"role": "model", "parts": raw}
    assert contents[2] == {
        "role": "user",
        "parts": [{"functionResponse": {"name": "t", "id": "fc1", "response": {"output": "42"}}}],
    }


def test_history_is_rebuilt_when_there_is_no_provider_state() -> None:
    contents = to_gemini_contents(
        [
            {"role": "user", "text": "go"},
            {
                "role": "assistant",
                "text": "thinking",
                "tool_calls": [{"id": "call_0", "name": "t", "args": {}}],
                "provider_state": None,
            },
            {
                "role": "tool",
                "results": [{"id": "call_0", "name": "t", "content": "bad", "is_error": True}],
            },
        ]
    )
    assert contents[1]["parts"] == [
        {"text": "thinking"},
        {"functionCall": {"name": "t", "args": {}}},
    ]
    # Without a provider-issued id, none is sent back; an error result is labelled as one.
    assert contents[2]["parts"] == [
        {"functionResponse": {"name": "t", "response": {"error": "bad"}}}
    ]


def test_parallel_results_are_matched_to_calls_by_position() -> None:
    raw = [{"functionCall": {"name": "a", "args": {}}}, {"functionCall": {"name": "b", "args": {}}}]
    contents = to_gemini_contents(
        [
            {"role": "user", "text": "go"},
            {"role": "assistant", "text": "", "tool_calls": [], "provider_state": raw},
            {
                "role": "tool",
                "results": [
                    {"id": "call_0", "name": "a", "content": "A", "is_error": False},
                    {"id": "call_1", "name": "b", "content": "B", "is_error": False},
                ],
            },
        ]
    )
    names = [p["functionResponse"]["name"] for p in contents[2]["parts"]]
    assert names == ["a", "b"]


# ---------- the response ----------


async def test_text_answer_and_usage() -> None:
    gemini = client(lambda r: httpx.Response(200, json=answer([{"text": "Hel"}, {"text": "lo"}])))
    response = await complete(gemini)
    assert response.text == "Hello"
    assert response.finish is FinishReason.STOP
    assert (response.input_tokens, response.output_tokens) == (11, 7)


async def test_thinking_tokens_are_billed_as_output() -> None:
    body = answer([{"text": "x"}])
    body["usageMetadata"]["thoughtsTokenCount"] = 100
    response = await complete(client(lambda r: httpx.Response(200, json=body)))
    assert response.output_tokens == 107


async def test_function_calls_are_parsed_and_the_raw_parts_are_kept() -> None:
    parts = [
        {
            "functionCall": {"name": "utility_calculate", "args": {"expression": "1+1"}},
            "thoughtSignature": "S1",
        },
        {"functionCall": {"name": "utility_current_time", "args": {}, "id": "abc"}},
    ]
    response = await complete(client(lambda r: httpx.Response(200, json=answer(parts))))
    assert response.finish is FinishReason.TOOL_CALLS
    assert [(c.id, c.name, c.args) for c in response.tool_calls] == [
        ("call_0", "utility_calculate", {"expression": "1+1"}),
        ("abc", "utility_current_time", {}),
    ]
    assert response.provider_state == parts


async def test_thought_summaries_are_not_shown_as_the_answer() -> None:
    parts = [{"text": "private reasoning", "thought": True}, {"text": "The answer."}]
    response = await complete(client(lambda r: httpx.Response(200, json=answer(parts))))
    assert response.text == "The answer."
    assert response.provider_state == parts  # still replayed to the model


async def test_missing_args_become_an_empty_object() -> None:
    parts = [{"functionCall": {"name": "utility_current_time"}}]
    response = await complete(client(lambda r: httpx.Response(200, json=answer(parts))))
    assert response.tool_calls[0].args == {}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("MAX_TOKENS", FinishReason.MAX_TOKENS),
        ("SAFETY", FinishReason.REFUSED),
        ("PROHIBITED_CONTENT", FinishReason.REFUSED),
        ("RECITATION", FinishReason.REFUSED),
    ],
)
async def test_finish_reasons(reason: str, expected: FinishReason) -> None:
    body = answer([{"text": "partial"}])
    body["candidates"][0]["finishReason"] = reason
    response = await complete(client(lambda r: httpx.Response(200, json=body)))
    assert response.finish is expected


@pytest.mark.parametrize("reason", ["MALFORMED_FUNCTION_CALL", "OTHER"])
async def test_unusable_finish_reasons_are_errors(reason: str) -> None:
    body = answer([])
    body["candidates"][0]["finishReason"] = reason
    with pytest.raises(LLMError):
        await complete(client(lambda r: httpx.Response(200, json=body)))


async def test_a_blocked_prompt_is_a_refusal() -> None:
    body = {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"promptTokenCount": 3}}
    response = await complete(client(lambda r: httpx.Response(200, json=body)))
    assert response.finish is FinishReason.REFUSED
    assert response.input_tokens == 3


# ---------- failures ----------


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (401, "API key"),
        (403, "API key"),
        (404, "does not know the model"),
        (400, "rejected the request"),
        (429, "rate limiting"),
        (500, "temporarily unavailable"),
        (502, "temporarily unavailable"),
        (503, "overloaded right now"),
    ],
)
async def test_http_errors_become_safe_messages(status: int, fragment: str) -> None:
    body = {"error": {"message": f"details with {SECRET} and a prompt"}}
    gemini = client(lambda r: httpx.Response(status, json=body))
    with pytest.raises(LLMError) as info:
        await complete(gemini)
    assert fragment in str(info.value)
    assert SECRET not in str(info.value)
    assert "prompt" not in str(info.value)


async def test_rate_limits_and_server_errors_are_retried() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429 if attempts["n"] == 1 else 503, json={})
        return httpx.Response(200, json=answer([{"text": "finally"}]))

    response = await complete(client(handler, delays=(0.0, 0.0)))
    assert response.text == "finally"
    assert attempts["n"] == 3


async def test_retries_stop_after_the_last_delay() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(429, json={})

    with pytest.raises(LLMError):
        await complete(client(handler, delays=(0.0, 0.0)))
    assert attempts["n"] == 3


async def test_client_errors_are_not_retried() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(400, json={})

    with pytest.raises(LLMError):
        await complete(client(handler, delays=(0.0, 0.0)))
    assert attempts["n"] == 1


async def test_slow_answers_and_unreachable_networks_get_different_messages() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    def no_route(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route", request=request)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError, match=r"'gemini-x' did not answer within 5 seconds.*overloaded"):
        await complete(client(slow))
    with pytest.raises(LLMError, match="could not be reached"):
        await complete(client(no_route))
    with pytest.raises(LLMError, match="could not be reached"):
        await complete(client(down))


async def test_an_overloaded_model_that_made_us_wait_is_not_retried() -> None:
    """Google took ~54 s to say 503 in practice; retrying that would blow the run's time limit."""
    attempts = {"n": 0}
    clock_values = iter([0.0, 54.0])  # request started at 0 s, failed at 54 s

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={})

    gemini = GeminiClient(
        api_key=SECRET,
        base_url="https://gemini.test/v1beta",
        timeout=60,
        retry_delays=(0.0, 0.0),
        transport=httpx.MockTransport(handler),
        clock=lambda: next(clock_values),
    )
    with pytest.raises(LLMError, match="overloaded right now"):
        await complete(gemini)
    assert attempts["n"] == 1
