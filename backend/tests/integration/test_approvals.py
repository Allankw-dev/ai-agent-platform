"""Approvals: a run pauses before a risky action and a person decides.

These tests drive the real engine, database and API. The calculator tool stands in for a risky
action (an agent can require approval for any tool), so the whole mechanism is exercised with no
outside service: pause, approve, reject, expire, cancel, resume, and every way those can race.
"""

import json
import uuid

import pytest

from app.engine.executor import execute_run
from tests.fakes import ScriptedLLM, call_tools, reply
from tests.integration.approval_helpers import (
    CALC,
    CLOCK,
    Maker,
    audit_actions,
    decide,
    one_sum,
    resume,
    start,
    tool_steps,
    waiting,
)
from tests.integration.engine_helpers import ADMIN, OWNER, Queue, Workspace


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue) -> None:
    """A (fake) model key and a recorder instead of Celery for every test here."""


# ---------- pausing ----------


async def test_a_run_pauses_for_approval_and_holds_no_worker(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    llm = one_sum("I will add the two numbers.")
    run_id = await start(workspace, runtime_maker, llm)

    run = await workspace.detail(run_id)
    assert run["status"] == "awaiting_approval" and run["finished_at"] is None
    assert [(s["step_type"], s["status"]) for s in run["steps"]] == [
        ("llm_call", "succeeded"),
        ("tool_call", "awaiting_approval"),
    ]
    step = tool_steps(run)[0]
    assert step["input"] == {"expression": "1 + 1"} and step["output"] is None  # not run
    assert llm.calls == 1  # the model is not asked again while the person decides
    assert queue.resumes == []  # nothing is queued: no worker is held

    approval = await waiting(workspace, run_id)
    assert approval["status"] == "pending"
    assert approval["tool_key"] == "utility.calculate"
    assert approval["tool_name"] == "Calculator"
    assert approval["proposed_input"] == {"expression": "1 + 1"}
    assert approval["reasoning_summary"] == "I will add the two numbers."
    assert approval["agent_name"] == "Helper" and approval["agent_version"] == 1
    assert approval["run_step_id"] == step["id"]
    assert approval["decided_by_id"] is None and approval["decided_at"] is None
    assert 86_000 < approval["seconds_left"] <= 86_400  # 24 hours by default

    # The run page can show "waiting for approval" and link to it.
    assert run["pending_approval"]["id"] == approval["id"]
    assert run["pending_approval"]["tool_key"] == "utility.calculate"


async def test_the_pause_saves_the_loop_state_on_the_run(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    checkpoint = json.loads(
        str(workspace.api.scalar("SELECT checkpoint::text FROM agent_runs WHERE id = :r", r=run_id))
    )
    assert checkpoint["version"] == 1
    assert [m["role"] for m in checkpoint["messages"]] == ["user", "assistant"]
    assert checkpoint["iterations"] == 1 and checkpoint["input_tokens"] == 10
    assert checkpoint["awaiting"]["tool_key"] == "utility.calculate"
    assert checkpoint["pending_tool_calls"] == [] and checkpoint["collected_results"] == []
    # The arguments live only in the approval, so what is approved is exactly what runs.
    assert "1 + 1" not in json.dumps(checkpoint["awaiting"])


async def test_the_request_is_audited_without_its_arguments(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    await start(workspace, runtime_maker, one_sum())
    assert audit_actions(workspace) == ["approval.requested"]
    details = str(
        workspace.api.scalar(
            "SELECT details::text FROM audit_logs WHERE action = 'approval.requested'"
        )
    )
    assert "1 + 1" not in details and "utility.calculate" in details
    assert workspace.api.scalar(
        "SELECT actor_user_id IS NULL FROM audit_logs WHERE action = 'approval.requested'"
    )


async def test_arguments_that_break_the_rules_never_reach_a_person(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(call_tools(("utility_calculate", {"wrong": 1})), reply("Sorry."))
    run_id = await start(workspace, runtime_maker, llm)
    run = await workspace.detail(run_id)
    assert run["status"] == "succeeded"
    assert tool_steps(run)[0]["status"] == "failed"
    assert workspace.api.scalar("SELECT count(*) FROM approvals") == 0


async def test_a_tool_that_needs_no_approval_runs_straight_away(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(call_tools(("utility_current_time", {})), reply("Done."))
    run_id = await start(workspace, runtime_maker, llm, tools=[CLOCK])
    run = await workspace.detail(run_id)
    assert run["status"] == "succeeded" and run["pending_approval"] is None
    assert workspace.api.scalar("SELECT count(*) FROM approvals") == 0


# ---------- approving ----------


async def test_approving_runs_the_stored_action_and_the_run_finishes(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)

    response = await decide(workspace, approval["id"], note="Looks right")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved" and body["decision_note"] == "Looks right"
    assert body["decided_by_name"] == OWNER and body["decided_at"] is not None
    assert queue.resumes == [(uuid.UUID(run_id), uuid.UUID(workspace.org_id))]
    # Deciding only hands the run back; the action has not run yet.
    assert (await workspace.detail(run_id))["status"] == "awaiting_approval"
    assert llm.calls == 1

    await resume(workspace, runtime_maker, llm, run_id)

    run = await workspace.detail(run_id)
    assert run["status"] == "succeeded" and run["output"]["text"] == "The answer is 2."
    assert run["pending_approval"] is None
    assert [(s["step_type"], s["status"]) for s in run["steps"]] == [
        ("llm_call", "succeeded"),
        ("tool_call", "succeeded"),
        ("llm_call", "succeeded"),
    ]
    assert tool_steps(run)[0]["output"] == {"expression": "1 + 1", "result": 2}
    # The model was told the result, exactly once, and the run's totals add up across the pause.
    result = llm.requests[1]["messages"][-1]["results"][0]
    assert result["is_error"] is False and json.loads(result["content"])["result"] == 2
    assert run["output"]["iterations"] == 2
    assert (run["input_tokens"], run["output_tokens"]) == (20, 10)
    assert workspace.api.scalar("SELECT checkpoint IS NULL FROM agent_runs WHERE id = :r", r=run_id)
    assert audit_actions(workspace) == ["approval.requested", "approval.approved"]


async def test_the_approved_action_is_never_asked_of_the_model_again(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    """A different request from the model after the pause could not change what runs."""
    llm = ScriptedLLM(
        call_tools(("utility_calculate", {"expression": "1 + 1"})), reply("The answer is 2.")
    )
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"])
    await resume(workspace, runtime_maker, llm, run_id)
    assert llm.calls == 2  # one request to pause, one after the action; none in between
    assert tool_steps(await workspace.detail(run_id))[0]["input"] == {"expression": "1 + 1"}


async def test_the_person_who_started_the_run_may_approve_it(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = one_sum()
    agent_id = await workspace.create_agent(who=ADMIN, tools=[CALC])
    started = await workspace.start_run(agent_id, who=ADMIN)
    run_id = str(started.json()["id"])
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    approval = await waiting(workspace, run_id)
    assert (await decide(workspace, approval["id"], who=ADMIN)).status_code == 200


# ---------- rejecting ----------


async def test_rejecting_tells_the_model_and_runs_nothing(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    llm = ScriptedLLM(
        call_tools(("utility_calculate", {"expression": "1 + 1"})),
        reply("Understood, I will not calculate it."),
    )
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)

    response = await decide(workspace, approval["id"], "reject", note="Use a spreadsheet instead")
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert queue.resumes  # the model must still be told
    await resume(workspace, runtime_maker, llm, run_id)

    run = await workspace.detail(run_id)
    assert run["status"] == "succeeded" and run["output"]["text"].startswith("Understood")
    step = tool_steps(run)[0]
    assert step["status"] == "skipped" and step["output"] is None  # never ran
    assert "rejected" in step["error"] and "Use a spreadsheet instead" in step["error"]
    told = llm.requests[1]["messages"][-1]["results"][0]
    assert told["is_error"] is True
    assert "A person rejected this action" in told["content"]
    assert "Use a spreadsheet instead" in told["content"]
    assert audit_actions(workspace) == ["approval.requested", "approval.rejected"]
    assert "Use a spreadsheet" not in str(
        workspace.api.scalar("SELECT string_agg(details::text, ' ') FROM audit_logs")
    )  # the note is recorded on the approval, not copied into the audit log


async def test_a_rejection_without_a_note_is_fine(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(call_tools(("utility_calculate", {"expression": "2 * 2"})), reply("OK."))
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    assert (await decide(workspace, approval["id"], "reject")).status_code == 200
    await resume(workspace, runtime_maker, llm, run_id)
    told = llm.requests[1]["messages"][-1]["results"][0]["content"]
    assert told == "A person rejected this action, so it was not run."


# ---------- the action itself can still fail ----------


async def test_an_approved_action_that_fails_is_reported_to_the_model(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(
        call_tools(("utility_calculate", {"expression": "1 / 0"})), reply("That cannot be done.")
    )
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"])
    await resume(workspace, runtime_maker, llm, run_id)
    run = await workspace.detail(run_id)
    assert run["status"] == "succeeded"
    assert tool_steps(run)[0]["status"] == "failed"
    assert llm.requests[1]["messages"][-1]["results"][0]["is_error"] is True


# ---------- several tool calls in one reply ----------


async def test_calls_in_one_reply_run_in_order_and_pause_at_each_approval(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(
        call_tools(
            ("utility_current_time", {}),  # call_0: free
            ("utility_calculate", {"expression": "1 + 1"}),  # call_1: needs approval
            ("utility_current_time", {}),  # call_2: free
            ("utility_calculate", {"expression": "2 + 2"}),  # call_3: needs approval
        ),
        reply("All done."),
    )
    run_id = await start(workspace, runtime_maker, llm, tools=[CALC, CLOCK])

    # First pause: the free call before it already ran; nothing after it has.
    run = await workspace.detail(run_id)
    assert [(s["tool_key"], s["status"]) for s in tool_steps(run)] == [
        ("utility.current_time", "succeeded"),
        ("utility.calculate", "awaiting_approval"),
    ]
    first = await waiting(workspace, run_id)
    assert first["proposed_input"] == {"expression": "1 + 1"}
    await decide(workspace, first["id"])
    await resume(workspace, runtime_maker, llm, run_id)

    # Second pause: the approved call and the free one after it ran, then it stops again.
    run = await workspace.detail(run_id)
    assert run["status"] == "awaiting_approval"
    assert [(s["tool_key"], s["status"]) for s in tool_steps(run)] == [
        ("utility.current_time", "succeeded"),
        ("utility.calculate", "succeeded"),
        ("utility.current_time", "succeeded"),
        ("utility.calculate", "awaiting_approval"),
    ]
    assert llm.calls == 1  # still no new question to the model
    second = await waiting(workspace, run_id)
    assert second["id"] != first["id"] and second["proposed_input"] == {"expression": "2 + 2"}
    await decide(workspace, second["id"])
    await resume(workspace, runtime_maker, llm, run_id)

    run = await workspace.detail(run_id)
    assert run["status"] == "succeeded" and llm.calls == 2
    results = llm.requests[1]["messages"][-1]["results"]
    assert [r["id"] for r in results] == ["call_0", "call_1", "call_2", "call_3"]  # original order
    assert [
        json.loads(r["content"]).get("result") for r in results if r["name"] == "utility_calculate"
    ] == [2, 4]
    assert all(not r["is_error"] for r in results)


async def test_one_rejection_does_not_stop_the_other_calls(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(
        call_tools(("utility_calculate", {"expression": "1 + 1"}), ("utility_current_time", {})),
        reply("Partly done."),
    )
    run_id = await start(workspace, runtime_maker, llm, tools=[CALC, CLOCK])
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"], "reject")
    await resume(workspace, runtime_maker, llm, run_id)
    results = llm.requests[1]["messages"][-1]["results"]
    assert [r["is_error"] for r in results] == [True, False]
    assert (await workspace.detail(run_id))["status"] == "succeeded"
