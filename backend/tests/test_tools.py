import uuid
from typing import Any

import pytest

from app.tools import get_handler, registered_keys
from app.tools.base import (
    ToolArgumentsError,
    ToolContext,
    ToolDefinition,
    ToolError,
    validate_arguments,
)

CONTEXT = ToolContext(org_id=uuid.uuid4(), agent_id=uuid.uuid4(), run_id=uuid.uuid4())

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"expression": {"type": "string", "maxLength": 10}, "n": {"type": "integer"}},
    "required": ["expression"],
    "additionalProperties": False,
}


async def _calc(expression: str) -> Any:
    handler = get_handler("utility.calculate")
    assert handler is not None
    return (await handler({"expression": expression}, CONTEXT))["result"]


def _tool(**overrides: Any) -> ToolDefinition:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "key": "slack.send_message",
        "description": "d",
        "input_schema": {},
        "is_sensitive": False,
        "timeout_seconds": 5,
    }
    return ToolDefinition(**{**values, **overrides})


# ---------- registry ----------


def test_builtin_handlers_are_registered() -> None:
    assert {"utility.current_time", "utility.calculate"} <= registered_keys()
    assert get_handler("nope.nothing") is None


# ---------- definitions ----------


def test_model_facing_names_only_use_allowed_characters() -> None:
    assert _tool(key="slack.send_message").llm_name == "slack_send_message"
    assert _tool(key="a.b/c d").llm_name == "a_b_c_d"
    assert len(_tool(key="x" * 100).llm_name) == 64


def test_sensitive_tools_always_need_approval() -> None:
    assert _tool(is_sensitive=True, requires_approval=False).needs_approval
    assert _tool(is_sensitive=False, requires_approval=True).needs_approval
    assert not _tool().needs_approval


def test_for_llm_exposes_name_description_and_schema_only() -> None:
    spec = _tool(input_schema={"type": "object"}).for_llm()
    assert set(spec) == {"name", "description", "input_schema"}


# ---------- argument validation ----------


def test_valid_arguments_pass() -> None:
    assert validate_arguments(SCHEMA, {"expression": "1+1"}) == {"expression": "1+1"}


@pytest.mark.parametrize(
    "arguments",
    [
        {},  # missing required
        {"expression": 5},  # wrong type
        {"expression": "x" * 11},  # too long
        {"expression": "1", "extra": True},  # unknown property
        {"expression": "1", "n": "three"},
    ],
)
def test_invalid_arguments_are_rejected_with_a_short_reason(arguments: dict[str, Any]) -> None:
    with pytest.raises(ToolArgumentsError) as info:
        validate_arguments(SCHEMA, arguments)
    assert str(info.value).startswith("Invalid arguments.")
    assert len(str(info.value)) <= 500


@pytest.mark.parametrize("arguments", [None, "text", 5, ["a"]])
def test_arguments_must_be_an_object(arguments: Any) -> None:
    with pytest.raises(ToolArgumentsError):
        validate_arguments(SCHEMA, arguments)


# ---------- utility.calculate ----------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("7 // 2", 3),
        ("7 % 4", 3),
        ("2 ** 10", 1024),
        ("-5 + 2", -3),
        ("1200 * 0.16 + 45", 237.0),
        ("10 / 4", 2.5),
    ],
)
async def test_calculator_evaluates_arithmetic(expression: str, expected: float) -> None:
    assert await _calc(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd')",
        "abs(-1)",
        "x + 1",
        "'a' * 3",
        "[1, 2]",
        "1 if True else 2",
        "True + 1",
        "lambda: 1",
        "1 +",
        "",
        "(" * 300 + "1" + ")" * 300,
    ],
)
async def test_calculator_rejects_everything_but_arithmetic(expression: str) -> None:
    with pytest.raises(ToolError):
        await _calc(expression)


@pytest.mark.parametrize(
    "expression",
    ["9 ** 9 ** 9", "10 ** 101", "10 ** 60 * 10 ** 60", "2 ** 101", "1 / 0", "5 // 0", "5 % 0"],
)
async def test_calculator_cannot_be_used_to_burn_cpu_or_memory(expression: str) -> None:
    with pytest.raises(ToolError):
        await _calc(expression)


# ---------- utility.current_time ----------


async def test_current_time_defaults_to_utc_and_honors_timezones() -> None:
    handler = get_handler("utility.current_time")
    assert handler is not None
    utc = await handler({}, CONTEXT)
    assert utc["timezone"] == "UTC"
    assert utc["iso"].endswith("+00:00")
    nairobi = await handler({"timezone": "Africa/Nairobi"}, CONTEXT)
    assert nairobi["iso"].endswith("+03:00")


@pytest.mark.parametrize("name", ["Mars/Base", "", "../../etc/passwd", "x" * 200])
async def test_current_time_rejects_unknown_timezones(name: str) -> None:
    handler = get_handler("utility.current_time")
    assert handler is not None
    with pytest.raises(ToolError):
        await handler({"timezone": name}, CONTEXT)
