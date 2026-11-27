"""The saved state of a run that waits for a person: plain JSON that round-trips exactly."""

import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.engine.graph import (
    CHECKPOINT_VERSION,
    EngineState,
    checkpoint_from_state,
    idempotency_key,
    initial_state,
    progress_checkpoint,
    state_from_checkpoint,
    state_from_progress,
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
            "tool_calls": 2,
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


def test_the_tool_call_count_survives_a_pause() -> None:
    checkpoint = json.loads(json.dumps(checkpoint_from_state(paused_state())))
    assert checkpoint["tool_calls"] == 2
    rebuilt = state_from_checkpoint(checkpoint, decision="approved", note=None, arguments={})
    assert rebuilt["tool_calls"] == 2


def test_a_run_paused_before_the_counter_existed_resumes_with_zero() -> None:
    checkpoint = json.loads(json.dumps(checkpoint_from_state(paused_state())))
    del checkpoint["tool_calls"]  # what an older worker saved
    rebuilt = state_from_checkpoint(checkpoint, decision="approved", note=None, arguments={})
    assert rebuilt["tool_calls"] == 0


def test_a_pause_checkpoint_is_marked_as_one() -> None:
    assert checkpoint_from_state(paused_state())["kind"] == "pause"


def test_progress_is_plain_json_and_rebuilds_the_same_loop_state() -> None:
    state = paused_state()
    state["awaiting"] = {}
    saved = json.loads(json.dumps(progress_checkpoint(state)))
    assert saved["kind"] == "progress" and saved["version"] == CHECKPOINT_VERSION
    rebuilt = state_from_progress(saved)
    for key in (
        "messages",
        "pending_tool_calls",
        "collected_results",
        "iterations",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "cost_micro_usd",
        "final_text",
    ):
        assert rebuilt[key] == state[key], key
    assert rebuilt["resume"] is None and rebuilt["outcome"] == ""


def test_progress_after_a_resume_notes_only_which_approval_it_answers() -> None:
    state = paused_state()
    state["resume"] = {
        "awaiting": {"approval_id": "a-1", "step_id": "s-1"},
        "decision": "approved",
        "note": "fine",
        "arguments": {"expression": "secret-looking arguments"},
    }
    saved = progress_checkpoint(state)
    assert saved["resume"] == {"awaiting": {"approval_id": "a-1", "step_id": "s-1"}}
    assert "secret-looking" not in json.dumps(saved["resume"])


def test_progress_and_pause_checkpoints_are_not_mistaken_for_each_other() -> None:
    pause = checkpoint_from_state(paused_state())
    with pytest.raises(ValueError):
        state_from_progress(pause)
    progress = progress_checkpoint(paused_state())
    with pytest.raises(ValueError):
        state_from_checkpoint(progress, decision="approved", note=None, arguments={})


@pytest.mark.parametrize("version", [0, 2, 99, "1", None])
def test_progress_in_an_unknown_format_is_refused_not_guessed(version: Any) -> None:
    saved = progress_checkpoint(paused_state())
    saved["version"] = version
    with pytest.raises(ValueError):
        state_from_progress(saved)


def test_progress_saved_before_the_tool_call_counter_existed_reads_zero() -> None:
    saved = progress_checkpoint(paused_state())
    del saved["tool_calls"]
    assert state_from_progress(saved)["tool_calls"] == 0


RUN = uuid.UUID("11111111-2222-3333-4444-555555555555")


def test_a_calls_idempotency_key_is_stable_and_names_that_call_only() -> None:
    first = idempotency_key(RUN, "2.0")
    assert first == idempotency_key(RUN, "2.0")  # the same after a crash and a recovery
    assert first != idempotency_key(RUN, "2.1")  # another call of the reply
    assert first != idempotency_key(RUN, "3.0")  # the same position in another reply
    assert first != idempotency_key(uuid.uuid4(), "2.0")  # another run
    assert uuid.UUID(str(first)).version == 5  # a UUID, safe for any service to accept


def test_a_call_without_a_key_has_no_idempotency_key() -> None:
    assert idempotency_key(RUN, None) is None
