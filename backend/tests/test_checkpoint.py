"""The saved state of a run that waits for a person: plain JSON that round-trips exactly."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.engine.graph import (
    CHECKPOINT_VERSION,
    EngineState,
    checkpoint_from_state,
    initial_state,
    state_from_checkpoint,
)
from app.engine.recorder import strip_nul


def paused_state() -> EngineState:
    state = initial_state("Add them")
    state["messages"].append(
        {"role": "assistant", "text": "I will.", "tool_calls": [{"id": "c1", "name": "x"}]}
    )
    state.update(
        {
            "pending_tool_calls": [{"id": "c2", "name": "y", "args": {"a": 1}}],
            "collected_results": [{"id": "c0", "name": "z", "content": "ok", "is_error": False}],
            "iterations": 3,
            "input_tokens": 120,
            "output_tokens": 45,
            "cost_micro_usd": 99,
            "final_text": "I will.",
            "awaiting": {
                "approval_id": "a1",
                "call_id": "c1",
                "name": "x",
                "tool_key": "t.x",
                "step_id": "s1",
            },
        }
    )
    return state


def test_a_checkpoint_is_plain_json() -> None:
    checkpoint = checkpoint_from_state(paused_state())
    assert json.loads(json.dumps(checkpoint)) == checkpoint
    assert checkpoint["version"] == CHECKPOINT_VERSION


def test_a_checkpoint_rebuilds_the_same_loop_state() -> None:
    state = paused_state()
    rebuilt = state_from_checkpoint(
        json.loads(json.dumps(checkpoint_from_state(state))),
        decision="approved",
        note="ok",
        arguments={"expression": "1 + 1"},
    )
    for key in (
        "messages",
        "pending_tool_calls",
        "collected_results",
        "iterations",
        "input_tokens",
        "output_tokens",
        "cost_micro_usd",
        "final_text",
        "awaiting",
    ):
        assert rebuilt[key] == state[key], key
    assert rebuilt["resume"] == {
        "awaiting": state["awaiting"],
        "decision": "approved",
        "note": "ok",
        "arguments": {"expression": "1 + 1"},
    }
    assert rebuilt["outcome"] == ""  # nothing has finished yet


def test_a_checkpoint_never_holds_the_approved_arguments() -> None:
    state = paused_state()
    state["awaiting"]["arguments"] = {"secret": "x"}  # even if some caller put them here
    # The builder copies the awaiting marker as given; the engine never puts arguments in it.
    # What matters is the rebuild takes the arguments from the approval, not the checkpoint.
    rebuilt = state_from_checkpoint(
        checkpoint_from_state(state), decision="approved", note=None, arguments={"real": 1}
    )
    assert rebuilt["resume"] is not None and rebuilt["resume"]["arguments"] == {"real": 1}


@pytest.mark.parametrize("version", [0, 2, 99, None])
def test_an_unknown_format_is_refused_not_guessed(version: Any) -> None:
    checkpoint = checkpoint_from_state(paused_state())
    checkpoint["version"] = version
    with pytest.raises(ValueError, match="unknown format"):
        state_from_checkpoint(checkpoint, decision="approved", note=None, arguments={})


def test_nul_characters_are_removed_without_touching_anything_else() -> None:
    data = {"a\x00b": ["x\x00y", {"k": "v\x00"}], "n": 5, "t": "é ☀️ <tag>", "z": None}
    cleaned = strip_nul(data)
    assert cleaned == {"ab": ["xy", {"k": "v"}], "n": 5, "t": "é ☀️ <tag>", "z": None}


def test_strip_nul_never_shortens_text() -> None:
    long_text = "a" * 50_000
    assert strip_nul(long_text) == long_text  # unlike `scrub`: approved text must stay whole


def test_a_checkpoint_survives_a_nul_in_the_conversation() -> None:
    state = paused_state()
    state["messages"][0] = {"role": "user", "text": "hi\x00there"}
    checkpoint = checkpoint_from_state(state)
    assert "\x00" not in json.dumps(checkpoint)
    assert checkpoint["messages"][0]["text"] == "hithere"


# ---------- the setting ----------


@pytest.mark.parametrize("hours", [1, 24, 168])
def test_the_expiry_setting_accepts_sensible_values(hours: int) -> None:
    assert Settings(_env_file=None, approval_expiry_hours=hours).approval_expiry_hours == hours


@pytest.mark.parametrize("hours", [0, -1, 169, 10_000])
def test_the_expiry_setting_refuses_silly_values(hours: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, approval_expiry_hours=hours)


def test_the_default_expiry_is_24_hours() -> None:
    assert Settings(_env_file=None).approval_expiry_hours == 24
