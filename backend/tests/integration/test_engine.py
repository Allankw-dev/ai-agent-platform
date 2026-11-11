"""The agent engine end to end: real database and API, scripted model, no network.

A run is created through the API, then executed exactly as the Celery worker does it
(`execute_run`), as the restricted runtime role, and the result is read back through the API.
"""

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.engine.executor import execute_run
from app.engine.llm import FinishReason, LLMError
from tests.fakes import ScriptedLLM, call_tools, reply, with_finish
from tests.integration.engine_helpers import MEMBER, Queue, Workspace

Maker = async_sessionmaker[AsyncSession]

CALC = {"tool_key": "utility.calculate"}
TIME = {"tool_key": "utility.current_time"}
PRICES = '{"gemini-test-model": {"input_per_mtok": "2", "output_per_mtok": "10"}}'


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue) -> None:
    """Every test here runs with a (fake) key and with Celery replaced by a recorder."""


@pytest.fixture
def prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PRICES", PRICES)
    get_settings.cache_clear()


async def run_agent(
    ws: Workspace,
    maker: Maker,
    llm: ScriptedLLM,
    *,
    message: str = "Hello",
    **config: Any,
) -> dict[str, Any]:
    """Create an agent, start a run, execute it with `llm`, and return the run detail."""
    agent_id = await ws.create_agent(**config)
    run_id = await ws.new_run(agent_id, message)
    await execute_run(uuid.UUID(run_id), uuid.UUID(ws.org_id), maker=maker, llm=llm)
    return await ws.detail(run_id)


def tool_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in run["steps"] if s["step_type"] == "tool_call"]


# ---------- the happy path ----------


async def test_a_simple_answer(workspace: Workspace, runtime_maker: Maker, prices: None) -> None:
    llm = ScriptedLLM(reply("Hi there", tokens_in=1000, tokens_out=500))
    run = await run_agent(workspace, runtime_maker, llm)

    assert run["status"] == "succeeded"
    assert run["output"] == {"text": "Hi there", "iterations": 1}
    assert run["error"] is None
    assert (run["input_tokens"], run["output_tokens"]) == (1000, 500)
    assert run["cost_usd"] == pytest.approx(0.007)  # $2/M in + $10/M out
    assert run["started_at"] and run["finished_at"]
    assert [s["step_type"] for s in run["steps"]] == ["llm_call"]
    assert run["steps"][0]["status"] == "succeeded"
    usage = workspace.api.scalar(
        "SELECT count(*) FROM usage_records WHERE run_id = :r", r=run["id"]
    )
    assert usage == 1


async def test_cost_is_zero_when_no_price_is_configured(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run = await run_agent(workspace, runtime_maker, ScriptedLLM(reply("ok", tokens_in=999_999)))
    assert run["status"] == "succeeded"
    assert run["cost_usd"] == 0


async def test_the_model_receives_the_agents_configuration(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(reply("ok"))
    await run_agent(
        workspace,
        runtime_maker,
        llm,
        message="What is 2+2?",
        system_instructions="You are Ada.",
        objectives="Be concise.",
        model_params={"max_output_tokens": 321},
        tools=[CALC],
    )
    request = llm.requests[0]
    assert request["model"] == "gemini-test-model"
    assert request["system"] == "You are Ada.\n\nObjectives:\nBe concise."
    assert request["max_output_tokens"] == 321
    assert request["messages"] == [{"role": "user", "text": "What is 2+2?"}]
    assert [t["name"] for t in request["tools"]] == ["utility_calculate"]
    assert request["tools"][0]["input_schema"]["required"] == ["expression"]


async def test_a_run_uses_the_version_that_was_current_when_it_started(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent_id = await workspace.create_agent(system_instructions="Version one rules.")
    run_id = await workspace.new_run(agent_id)
    # The agent is edited while the run waits in the queue.
    new = await workspace.api.post(
        "dev@acme.example.com",
        f"{workspace.base}/agents/{agent_id}/versions",
        json={"config": {**_config(), "system_instructions": "Version two rules."}},
    )
    assert new.status_code == 201
    llm = ScriptedLLM(reply("ok"))
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    assert llm.requests[0]["system"] == "Version one rules."
    assert (await workspace.detail(run_id))["agent_version"] == 1


def _config() -> dict[str, Any]:
    return {"provider": "gemini", "model": "gemini-test-model", "system_instructions": "x"}


# ---------- tools ----------


async def test_the_tool_loop(workspace: Workspace, runtime_maker: Maker) -> None:
    llm = ScriptedLLM(
        call_tools(("utility_calculate", {"expression": "2 + 3 * 4"})),
        reply("It is 14."),
    )
    run = await run_agent(workspace, runtime_maker, llm, tools=[CALC])

    assert run["status"] == "succeeded"
    assert run["output"]["text"] == "It is 14."
    assert run["output"]["iterations"] == 2
    assert [s["step_type"] for s in run["steps"]] == ["llm_call", "tool_call", "llm_call"]
    assert [s["sequence"] for s in run["steps"]] == [0, 1, 2]
    (step,) = tool_steps(run)
    assert step["status"] == "succeeded"
    assert step["tool_key"] == "utility.calculate"
    assert step["input"] == {"expression": "2 + 3 * 4"}
    assert step["output"] == {"expression": "2 + 3 * 4", "result": 14}

    # The model got the result back, and nothing was flagged as an error.
    results = llm.requests[1]["messages"][-1]
    assert results["role"] == "tool"
    assert json.loads(results["results"][0]["content"])["result"] == 14
    assert results["results"][0]["is_error"] is False


async def test_the_providers_raw_reply_is_sent_back_unchanged(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    """Gemini 3+ rejects tool-calling history unless its thought signatures come back verbatim."""
    first = call_tools(("utility_current_time", {}))
    llm = ScriptedLLM(first, reply("done"))
    await run_agent(workspace, runtime_maker, llm, tools=[TIME])
    replayed = llm.requests[1]["messages"][1]
    assert replayed["role"] == "assistant"
    assert replayed["provider_state"] == first.provider_state


async def test_parallel_tool_calls_run_in_order(workspace: Workspace, runtime_maker: Maker) -> None:
    llm = ScriptedLLM(
        call_tools(
            ("utility_calculate", {"expression": "1+1"}),
            ("utility_calculate", {"expression": "2*3"}),
        ),
        reply("2 and 6"),
    )
    run = await run_agent(workspace, runtime_maker, llm, tools=[CALC])
    assert [s["output"]["result"] for s in tool_steps(run)] == [2, 6]
    results = llm.requests[1]["messages"][-1]["results"]
    assert [r["id"] for r in results] == ["call_0", "call_1"]


async def test_invalid_arguments_are_reported_to_the_model_not_executed(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(
        call_tools(("utility_calculate", {"expression": 5, "extra": True})),
        reply("Sorry, I will fix that."),
    )
    run = await run_agent(workspace, runtime_maker, llm, tools=[CALC])
    assert run["status"] == "succeeded"
    (step,) = tool_steps(run)
    assert step["status"] == "failed"
    assert step["error"].startswith("Invalid arguments.")
    assert step["output"] is None
    assert llm.requests[1]["messages"][-1]["results"][0]["is_error"] is True


async def test_a_tool_the_model_invents_is_refused(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(call_tools(("delete_everything", {})), reply("ok"))
    run = await run_agent(workspace, runtime_maker, llm, tools=[CALC])
    (step,) = tool_steps(run)
    assert step["status"] == "failed"
    assert "not available" in step["error"]


async def test_a_real_tool_the_agent_was_not_given_is_refused(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(call_tools(("utility_calculate", {"expression": "1+1"})), reply("ok"))
    run = await run_agent(workspace, runtime_maker, llm, tools=[TIME])  # calculator not granted
    (step,) = tool_steps(run)
    assert step["status"] == "failed"
    assert "not available" in step["error"]
    assert step["output"] is None


async def test_a_tool_that_needs_approval_is_not_run(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(call_tools(("utility_calculate", {"expression": "1+1"})), reply("ok"))
    run = await run_agent(
        workspace,
        runtime_maker,
        llm,
        tools=[{"tool_key": "utility.calculate", "requires_approval": True}],
    )
    (step,) = tool_steps(run)
    assert step["status"] == "skipped"
    assert "approval" in step["error"]
    assert step["output"] is None  # the handler never ran
    assert llm.requests[1]["messages"][-1]["results"][0]["is_error"] is True


async def test_tool_failures_never_leak_internals(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tools as registry

    async def boom(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
        raise RuntimeError("password=hunter2 in /srv/secret/path")

    async def slow(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {}

    for key, handler, seconds in (("test.boom", boom, 5), ("test.slow", slow, 1)):
        workspace.api.execute(
            "INSERT INTO tools (key, name, description, input_schema, timeout_seconds) "
            "VALUES (:k, :k, 'test tool', CAST('{\"type\": \"object\"}' AS jsonb), :t)",
            k=key,
            t=seconds,
        )
        monkeypatch.setitem(registry._HANDLERS, key, handler)

    llm = ScriptedLLM(call_tools(("test_boom", {}), ("test_slow", {})), reply("handled"))
    run = await run_agent(
        workspace,
        runtime_maker,
        llm,
        tools=[{"tool_key": "test.boom"}, {"tool_key": "test.slow"}],
    )
    assert run["status"] == "succeeded"
    boom_step, slow_step = tool_steps(run)
    assert boom_step["error"] == "The tool failed unexpectedly."
    assert slow_step["error"] == "The tool timed out after 1 seconds."
    assert "hunter2" not in json.dumps(run)
    assert "hunter2" not in json.dumps(llm.requests[1]["messages"])


# ---------- limits ----------


async def test_the_iteration_limit_stops_a_looping_agent(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    call = call_tools(("utility_calculate", {"expression": "1+1"}))
    llm = ScriptedLLM(call, call)
    run = await run_agent(workspace, runtime_maker, llm, tools=[CALC], limits={"max_iterations": 2})
    assert run["status"] == "failed"
    assert run["error"] == "Stopped: the agent reached its limit of 2 model calls."
    assert llm.calls == 2
    assert len(run["steps"]) == 4


async def test_the_token_limit(workspace: Workspace, runtime_maker: Maker) -> None:
    llm = ScriptedLLM(
        call_tools(("utility_calculate", {"expression": "1"}), tokens_in=600, tokens_out=500)
    )
    run = await run_agent(
        workspace, runtime_maker, llm, tools=[CALC], limits={"max_total_tokens": 1000}
    )
    assert run["status"] == "failed"
    assert run["error"] == "Stopped: the agent reached its limit of 1000 tokens."
    assert llm.calls == 1


async def test_the_cost_budget(workspace: Workspace, runtime_maker: Maker, prices: None) -> None:
    llm = ScriptedLLM(
        call_tools(("utility_calculate", {"expression": "1"}), tokens_in=1000, tokens_out=500)
    )
    run = await run_agent(
        workspace, runtime_maker, llm, tools=[CALC], limits={"cost_budget_usd": 0.001}
    )
    assert run["status"] == "failed"
    assert run["error"] == "Stopped: the agent reached its cost budget of $0.001."
    assert run["cost_usd"] == pytest.approx(0.007)
    assert llm.calls == 1


async def test_a_cost_budget_needs_a_configured_price(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM()
    run = await run_agent(workspace, runtime_maker, llm, limits={"cost_budget_usd": 1})
    assert run["status"] == "failed"
    assert "no price is configured" in run["error"]
    assert llm.calls == 0


async def test_the_time_limit(workspace: Workspace, runtime_maker: Maker) -> None:
    async def hang() -> Any:
        await asyncio.sleep(60)

    run = await run_agent(
        workspace, runtime_maker, ScriptedLLM(hang), limits={"timeout_seconds": 5}
    )
    assert run["status"] == "failed"
    assert run["error"] == "Stopped: the agent hit its 5 second time limit."


# ---------- the model misbehaving ----------


async def test_a_provider_error_fails_the_run_with_a_safe_message(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(LLMError("The AI provider could not be reached."))
    run = await run_agent(workspace, runtime_maker, llm)
    assert run["status"] == "failed"
    assert run["error"] == "The AI provider could not be reached."
    assert run["steps"][0]["status"] == "failed"
    assert run["input_tokens"] == 0


async def test_a_truncated_reply_fails_but_keeps_the_partial_text(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(with_finish(reply("Half an ans"), FinishReason.MAX_TOKENS))
    run = await run_agent(workspace, runtime_maker, llm)
    assert run["status"] == "failed"
    assert "max_output_tokens" in run["error"]
    assert run["output"]["text"] == "Half an ans"


@pytest.mark.parametrize(
    ("response", "fragment"),
    [
        (with_finish(reply(""), FinishReason.REFUSED), "declined"),
        (reply("   "), "empty reply"),
    ],
)
async def test_refusals_and_empty_replies_fail(
    workspace: Workspace, runtime_maker: Maker, response: Any, fragment: str
) -> None:
    run = await run_agent(workspace, runtime_maker, ScriptedLLM(response))
    assert run["status"] == "failed"
    assert fragment in run["error"]


async def test_an_unexpected_crash_fails_the_run_and_hides_the_details(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(RuntimeError("connection string postgres://user:pw@db"))
    run = await run_agent(workspace, runtime_maker, llm)
    assert run["status"] == "failed"
    assert run["error"] == "An internal error stopped this run."
    assert "postgres://" not in json.dumps(run)


# ---------- lifecycle ----------


async def test_cancelling_during_a_run_stops_it_and_stays_cancelled(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent_id = await workspace.create_agent(tools=[CALC])
    run_id = await workspace.new_run(agent_id)

    async def cancel_then_ask_for_a_tool() -> Any:
        cancelled = await workspace.api.post(
            "dev@acme.example.com", f"{workspace.base}/runs/{run_id}/cancel"
        )
        assert cancelled.status_code == 200
        return call_tools(("utility_calculate", {"expression": "1+1"}))

    llm = ScriptedLLM(cancel_then_ask_for_a_tool)
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    run = await workspace.detail(run_id)
    assert run["status"] == "cancelled"
    assert run["error"] is None
    assert llm.calls == 1  # no second model call after the cancellation


async def test_a_redelivered_running_run_is_failed_not_run_twice(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent_id = await workspace.create_agent()
    run_id = await workspace.new_run(agent_id)
    workspace.api.execute("UPDATE agent_runs SET status = 'running' WHERE id = :r", r=run_id)
    llm = ScriptedLLM()
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    run = await workspace.detail(run_id)
    assert run["status"] == "failed"
    assert "interrupted" in run["error"]
    assert llm.calls == 0


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
async def test_finished_runs_are_left_alone(
    workspace: Workspace, runtime_maker: Maker, status: str
) -> None:
    agent_id = await workspace.create_agent()
    run_id = await workspace.new_run(agent_id)
    workspace.api.execute("UPDATE agent_runs SET status = :s WHERE id = :r", s=status, r=run_id)
    llm = ScriptedLLM()
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    assert (await workspace.detail(run_id))["status"] == status
    assert llm.calls == 0


async def test_a_worker_acting_for_another_organization_cannot_touch_the_run(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    """Row Level Security: with the wrong organization the run does not exist."""
    agent_id = await workspace.create_agent()
    run_id = await workspace.new_run(agent_id)
    llm = ScriptedLLM(reply("should never run"))
    await execute_run(
        uuid.UUID(run_id), uuid.UUID(workspace.other_org_id), maker=runtime_maker, llm=llm
    )
    assert llm.calls == 0
    assert (await workspace.detail(run_id))["status"] == "queued"


async def test_a_missing_provider_key_fails_the_run_clearly(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_id = await workspace.create_agent()
    run_id = await workspace.new_run(agent_id)
    monkeypatch.delenv("GEMINI_API_KEY")  # the worker's environment has no key
    get_settings.cache_clear()
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker)
    run = await workspace.detail(run_id)
    assert run["status"] == "failed"
    assert "GEMINI_API_KEY" in run["error"]


async def test_members_can_read_a_runs_steps(workspace: Workspace, runtime_maker: Maker) -> None:
    llm = ScriptedLLM(call_tools(("utility_current_time", {})), reply("done"))
    agent_id = await workspace.create_agent(tools=[TIME])
    run_id = await workspace.new_run(agent_id)
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    run = await workspace.detail(run_id, who=MEMBER)
    assert [s["step_type"] for s in run["steps"]] == ["llm_call", "tool_call", "llm_call"]
