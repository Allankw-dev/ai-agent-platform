"""Crash recovery and idempotency of runs (Phase 5C).

A worker "dies" when something raises WorkerDied, a BaseException that no `except Exception` in the
engine catches: the run is left exactly as a killed process would leave it (status running, the step
in flight still running, nothing closed). A recovery then takes the run over and a replacement
worker carries on. The point of every test: however the worker dies, no action is carried out twice.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.config import get_settings
from app.engine import liveness
from app.engine.executor import BAD_CHECKPOINT, execute_run
from app.engine.llm import LLMResponse
from app.engine.recorder import RunRecorder
from app.engine.recovery import (
    INTERRUPTED_STEP,
    TOO_MANY_ATTEMPTS,
    UNRECOVERABLE,
    Verdict,
    recover_run,
    recover_stale_runs,
)
from app.repositories import runs as run_repo
from app.tools import _HANDLERS
from tests.fakes import ScriptedLLM, call_tools, reply
from tests.integration.approval_helpers import CALC, Maker, decide, resume, waiting
from tests.integration.engine_helpers import OWNER, Queue, Workspace

CALL = ("utility_calculate", {"expression": "1 + 1"})


class WorkerDied(BaseException):  # noqa: N818 (not an error: the process vanishing)
    """Raised to leave a run exactly as a killed worker would."""


class DyingLLM:
    """A model client whose call never returns: the worker is killed in the middle of it."""

    calls = 0

    async def complete(self, **_: Any) -> LLMResponse:
        self.calls += 1
        raise WorkerDied


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue) -> None:
    """A (fake) model key and a recorder instead of Celery for every test here."""


class Dispatched:
    """Stands in for Celery: remembers what recovery asked to have run again."""

    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def __call__(self, run_id: uuid.UUID, org_id: uuid.UUID) -> None:
        self.sent.append((run_id, org_id))


def far_future() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def ids(ws: Workspace, run_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.UUID(run_id), uuid.UUID(ws.org_id)


async def new_run(ws: Workspace, *, tools: list[dict[str, Any]] | None = None) -> str:
    name = f"Agent {uuid.uuid4().hex[:8]}"  # names are unique within an organization
    agent = await ws.create_agent(name=name, tools=tools if tools is not None else [])
    return await ws.new_run(agent)


async def work(ws: Workspace, maker: Maker, run_id: str, llm: Any, **kw: Any) -> None:
    run, org = ids(ws, run_id)
    await execute_run(run, org, maker=maker, llm=llm, **kw)


async def die(ws: Workspace, maker: Maker, run_id: str, llm: Any) -> None:
    """Run a worker until it 'dies' (WorkerDied escapes), leaving the run behind as it was."""
    with pytest.raises(WorkerDied):
        await work(ws, maker, run_id, llm)


async def take_over(
    ws: Workspace, maker: Maker, run_id: str, *, now: datetime | None = None
) -> tuple[Verdict, Dispatched]:
    dispatched = Dispatched()
    run, org = ids(ws, run_id)
    verdict = await recover_run(maker, org, run, dispatch=dispatched, now=now or far_future())
    return verdict, dispatched


async def events(ws: Workspace, run_id: str) -> list[str]:
    response = await ws.api.get(OWNER, f"{ws.base}/runs/{run_id}/events?limit=500")
    return [e["type"] for e in response.json()["items"]]


def step_states(run: dict[str, Any]) -> list[tuple[str, str]]:
    return [(s["step_type"], s["status"]) for s in run["steps"]]


class Counted:
    """Replaces the calculator's handler: counts how often it really ran, and can die doing it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, die_on: set[int] | None = None) -> None:
        self.runs = 0
        self._die_on = die_on or set()
        self._real = _HANDLERS["utility.calculate"]
        monkeypatch.setitem(_HANDLERS, "utility.calculate", self)

    async def __call__(self, arguments: dict[str, Any], context: Any) -> dict[str, Any]:
        self.runs += 1
        if self.runs in self._die_on:
            raise WorkerDied
        return await self._real(arguments, context)


def die_on_save(monkeypatch: pytest.MonkeyPatch, *, nth: int) -> None:
    """Make the nth save of the loop's progress kill the worker (after the work it follows)."""
    original = RunRecorder.save_progress
    seen = {"n": 0}

    async def flaky(self: RunRecorder, checkpoint: dict[str, Any]) -> None:
        seen["n"] += 1
        if seen["n"] == nth:
            raise WorkerDied
        await original(self, checkpoint)

    monkeypatch.setattr(RunRecorder, "save_progress", flaky)


# ---------- a worker lost at each point of a run ----------


async def test_a_worker_lost_during_the_first_model_call_is_replaced(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    await die(workspace, runtime_maker, run_id, DyingLLM())
    lost = await workspace.detail(run_id)
    assert lost["status"] == "running" and lost["attempt"] == 1
    assert step_states(lost) == [("llm_call", "running")]  # exactly as a killed process leaves it

    verdict, dispatched = await take_over(workspace, runtime_maker, run_id)
    assert verdict is Verdict.REQUEUED
    assert dispatched.sent == [ids(workspace, run_id)]
    queued = await workspace.detail(run_id)
    assert queued["status"] == "queued" and queued["attempt"] == 2
    assert (
        queued["steps"][0]["status"] == "failed" and queued["steps"][0]["error"] == INTERRUPTED_STEP
    )

    replacement = ScriptedLLM(reply("All done."))
    await work(workspace, runtime_maker, run_id, replacement)
    done = await workspace.detail(run_id)
    assert done["status"] == "succeeded" and done["output"]["text"] == "All done."
    assert done["attempt"] == 2
    assert step_states(done) == [("llm_call", "failed"), ("llm_call", "succeeded")]
    assert replacement.calls == 1
    assert await events(workspace, run_id) == [
        "run.queued",
        "run.started",
        "step.started",
        "run.recovered",
        "run.started",
        "step.started",
        "step.finished",
        "run.finished",
    ]
    audited = workspace.api.scalar(
        "SELECT count(*) FROM audit_logs WHERE action = 'run.recovered' AND resource_id = :r",
        r=run_id,
    )
    assert audited == 1


async def test_a_worker_lost_during_a_read_only_tool_runs_that_tool_again_and_nothing_else(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[{"tool_key": "utility.calculate"}])
    calculator = Counted(monkeypatch, die_on={1})
    first = ScriptedLLM(call_tools(CALL), reply("never reached"))
    await die(workspace, runtime_maker, run_id, first)
    assert first.calls == 1

    assert (await take_over(workspace, runtime_maker, run_id))[0] is Verdict.REQUEUED
    replacement = ScriptedLLM(reply("The answer is 2."))  # the first reply is not asked for again
    await work(workspace, runtime_maker, run_id, replacement)

    done = await workspace.detail(run_id)
    assert done["status"] == "succeeded"
    assert replacement.calls == 1
    assert calculator.runs == 2  # the interrupted try, and the retry
    assert step_states(done) == [
        ("llm_call", "succeeded"),
        ("tool_call", "failed"),  # interrupted
        ("tool_call", "succeeded"),
        ("llm_call", "succeeded"),
    ]
    assert done["steps"][1]["error"] == INTERRUPTED_STEP


async def test_a_tool_call_that_finished_before_the_crash_is_replayed_not_run_again(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[{"tool_key": "utility.calculate"}])
    calculator = Counted(monkeypatch)
    die_on_save(monkeypatch, nth=2)  # dies right after the tool finished, before saving progress
    await die(
        workspace,
        runtime_maker,
        run_id,
        ScriptedLLM(call_tools(CALL), reply("never reached")),
    )
    assert calculator.runs == 1
    assert step_states(await workspace.detail(run_id))[1] == ("tool_call", "succeeded")

    monkeypatch.undo()  # the replacement worker is healthy
    calculator = Counted(monkeypatch)
    assert (await take_over(workspace, runtime_maker, run_id))[0] is Verdict.REQUEUED
    replacement = ScriptedLLM(reply("The answer is 2."))
    await work(workspace, runtime_maker, run_id, replacement)

    done = await workspace.detail(run_id)
    assert done["status"] == "succeeded"
    assert calculator.runs == 0  # not run a second time: its recorded result was replayed
    tool_steps = [s for s in done["steps"] if s["step_type"] == "tool_call"]
    assert [s["status"] for s in tool_steps] == ["succeeded"]  # still one step, not two
    told = replacement.requests[0]["messages"][-1]
    assert "2" in str(told)  # the model was given the recorded result


async def test_replay_covers_every_call_of_a_reply_that_already_finished(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[{"tool_key": "utility.calculate"}])
    calculator = Counted(monkeypatch)
    two = call_tools(CALL, ("utility_calculate", {"expression": "2 * 3"}))
    die_on_save(monkeypatch, nth=3)  # after both calls finished, before the second save
    await die(workspace, runtime_maker, run_id, ScriptedLLM(two, reply("never reached")))
    assert calculator.runs == 2

    monkeypatch.undo()
    calculator = Counted(monkeypatch)
    await take_over(workspace, runtime_maker, run_id)
    await work(workspace, runtime_maker, run_id, ScriptedLLM(reply("Two and six.")))
    assert (await workspace.detail(run_id))["status"] == "succeeded"
    assert calculator.runs == 0


async def test_a_worker_lost_between_the_second_call_of_a_reply_resumes_at_that_call(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Progress is saved after each call, so the first call of a reply is never repeated."""
    run_id = await new_run(workspace, tools=[{"tool_key": "utility.calculate"}])
    calculator = Counted(monkeypatch, die_on={2})
    two = call_tools(CALL, ("utility_calculate", {"expression": "2 * 3"}))
    await die(workspace, runtime_maker, run_id, ScriptedLLM(two, reply("never reached")))
    assert calculator.runs == 2  # the first finished, the second was in flight

    await take_over(workspace, runtime_maker, run_id)
    await work(workspace, runtime_maker, run_id, ScriptedLLM(reply("Two and six.")))
    assert (await workspace.detail(run_id))["status"] == "succeeded"
    assert calculator.runs == 3  # only the interrupted second call ran again


# ---------- approved actions: never repeated ----------


async def test_an_approved_action_that_had_started_is_never_retried(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[CALC])
    llm = ScriptedLLM(call_tools(CALL), reply("The answer is 2."))
    await work(workspace, runtime_maker, run_id, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"], "approve")

    sensitive = Counted(monkeypatch, die_on={1})
    run, org = ids(workspace, run_id)
    from app.engine.executor import resume_run

    with pytest.raises(WorkerDied):
        await resume_run(run, org, maker=runtime_maker, llm=llm)
    assert sensitive.runs == 1

    verdict, dispatched = await take_over(workspace, runtime_maker, run_id)
    assert verdict is Verdict.FAILED
    assert dispatched.sent == []  # nothing is queued to try again
    failed = await workspace.detail(run_id)
    assert failed["status"] == "failed"
    assert run_repo.UNKNOWN_ACTION_RUN in failed["error"]
    assert sensitive.runs == 1
    assert [s["status"] for s in failed["steps"] if s["step_type"] == "tool_call"] == ["failed"]


async def test_an_approved_action_that_finished_is_not_repeated_after_the_crash(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[CALC])
    llm = ScriptedLLM(call_tools(CALL), reply("The answer is 2."))
    await work(workspace, runtime_maker, run_id, llm)
    await decide(workspace, (await waiting(workspace, run_id))["id"], "approve")

    action = Counted(monkeypatch)
    die_on_save(monkeypatch, nth=1)  # the first save after the action finished
    run, org = ids(workspace, run_id)
    from app.engine.executor import resume_run

    with pytest.raises(WorkerDied):
        await resume_run(run, org, maker=runtime_maker, llm=llm)
    assert action.runs == 1

    monkeypatch.undo()
    action = Counted(monkeypatch)
    assert (await take_over(workspace, runtime_maker, run_id))[0] is Verdict.REQUEUED
    await work(workspace, runtime_maker, run_id, llm)  # the replacement worker
    done = await workspace.detail(run_id)
    assert done["status"] == "succeeded", done["error"]
    assert action.runs == 0  # the approved action was not carried out a second time


async def test_a_worker_lost_before_an_approved_action_began_runs_it_exactly_once(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[CALC])
    llm = ScriptedLLM(call_tools(CALL), reply("The answer is 2."))
    await work(workspace, runtime_maker, run_id, llm)
    await decide(workspace, (await waiting(workspace, run_id))["id"], "approve")

    original = RunRecorder.mark_step_running

    async def dies_first(self: RunRecorder, step_id: uuid.UUID) -> bool:
        raise WorkerDied

    monkeypatch.setattr(RunRecorder, "mark_step_running", dies_first)
    run, org = ids(workspace, run_id)
    from app.engine.executor import resume_run

    with pytest.raises(WorkerDied):
        await resume_run(run, org, maker=runtime_maker, llm=llm)
    monkeypatch.setattr(RunRecorder, "mark_step_running", original)

    action = Counted(monkeypatch)
    assert (await take_over(workspace, runtime_maker, run_id))[0] is Verdict.REQUEUED
    await work(workspace, runtime_maker, run_id, llm)
    done = await workspace.detail(run_id)
    assert done["status"] == "succeeded", done["error"]
    assert action.runs == 1
    assert [s["status"] for s in done["steps"] if s["step_type"] == "tool_call"] == ["succeeded"]


async def test_a_worker_lost_between_asking_and_pausing_asks_a_person_only_once(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[CALC])
    llm = ScriptedLLM(call_tools(CALL), reply("The answer is 2."))

    async def never_pauses(*_: Any, **__: Any) -> bool:
        raise WorkerDied

    monkeypatch.setattr("app.engine.executor.run_repo.pause", never_pauses)
    await die(workspace, runtime_maker, run_id, llm)
    monkeypatch.undo()
    assert workspace.api.scalar("SELECT count(*) FROM approvals WHERE run_id = :r", r=run_id) == 1

    assert (await take_over(workspace, runtime_maker, run_id))[0] is Verdict.REQUEUED
    await work(workspace, runtime_maker, run_id, llm)
    paused = await workspace.detail(run_id)
    assert paused["status"] == "awaiting_approval"
    assert workspace.api.scalar("SELECT count(*) FROM approvals WHERE run_id = :r", r=run_id) == 1
    approval = await waiting(workspace, run_id)  # the same single request, still decidable

    action = Counted(monkeypatch)
    await decide(workspace, approval["id"], "approve")
    await resume(workspace, runtime_maker, llm, run_id)
    assert (await workspace.detail(run_id))["status"] == "succeeded"
    assert action.runs == 1


# ---------- when not to take a run over ----------


async def test_a_run_whose_worker_is_alive_is_left_alone(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    await die(workspace, runtime_maker, run_id, DyingLLM())  # the claim just set its heartbeat
    before = await workspace.detail(run_id)
    verdict, dispatched = await take_over(workspace, runtime_maker, run_id, now=datetime.now(UTC))
    assert verdict is Verdict.NOT_STALE and dispatched.sent == []
    after = await workspace.detail(run_id)
    assert (after["status"], after["attempt"]) == (before["status"], before["attempt"])


async def test_finished_cancelled_and_unknown_runs_are_not_touched(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    done = await new_run(workspace)
    await work(workspace, runtime_maker, done, ScriptedLLM(reply("Hi")))
    cancelled = await new_run(workspace)
    await workspace.api.post(OWNER, f"{workspace.base}/runs/{cancelled}/cancel")
    for run_id in (done, cancelled):
        verdict, dispatched = await take_over(workspace, runtime_maker, run_id)
        assert verdict is Verdict.GONE and dispatched.sent == []
    assert (await workspace.detail(done))["attempt"] == 1
    ghost = Dispatched()
    missing = await recover_run(
        runtime_maker,
        uuid.UUID(workspace.org_id),
        uuid.uuid4(),
        dispatch=ghost,
        now=far_future(),
    )
    assert missing is Verdict.GONE


async def test_a_run_with_nothing_saved_to_continue_from_is_ended_with_a_clear_message(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    workspace.api.execute(
        "UPDATE agent_runs SET status = 'running', started_at = now(), checkpoint = NULL "
        "WHERE id = :r",
        r=run_id,
    )
    verdict, dispatched = await take_over(workspace, runtime_maker, run_id)
    assert verdict is Verdict.FAILED and dispatched.sent == []
    failed = await workspace.detail(run_id)
    assert failed["status"] == "failed" and failed["error"] == UNRECOVERABLE


async def test_a_run_that_keeps_losing_its_worker_stops_after_the_attempt_limit(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    limit = get_settings().run_max_attempts
    run_id = await new_run(workspace)
    for attempt in range(1, limit):
        await die(workspace, runtime_maker, run_id, DyingLLM())
        verdict, _ = await take_over(workspace, runtime_maker, run_id)
        assert verdict is Verdict.REQUEUED
        assert (await workspace.detail(run_id))["attempt"] == attempt + 1
    await die(workspace, runtime_maker, run_id, DyingLLM())  # the last attempt dies too
    verdict, dispatched = await take_over(workspace, runtime_maker, run_id)
    assert verdict is Verdict.FAILED and dispatched.sent == []
    failed = await workspace.detail(run_id)
    assert failed["status"] == "failed" and failed["error"] == TOO_MANY_ATTEMPTS.format(n=limit)
    assert all(s["status"] != "running" for s in failed["steps"])


async def test_a_saved_state_in_an_unknown_format_ends_the_run_plainly(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    await die(workspace, runtime_maker, run_id, DyingLLM())
    workspace.api.execute(
        "UPDATE agent_runs SET checkpoint = jsonb_set(checkpoint, '{version}', '99') WHERE id = :r",
        r=run_id,
    )
    await take_over(workspace, runtime_maker, run_id)
    await work(workspace, runtime_maker, run_id, ScriptedLLM(reply("never")))
    failed = await workspace.detail(run_id)
    assert failed["status"] == "failed" and failed["error"] == BAD_CHECKPOINT


# ---------- being taken over exactly once ----------


async def test_simultaneous_recoverers_take_a_run_over_exactly_once(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    await die(workspace, runtime_maker, run_id, DyingLLM())
    dispatched = Dispatched()
    run, org = ids(workspace, run_id)
    verdicts = await asyncio.gather(
        *(
            recover_run(runtime_maker, org, run, dispatch=dispatched, now=far_future())
            for _ in range(8)
        )
    )
    assert sorted(v.value for v in verdicts) == ["gone"] * 7 + ["requeued"]
    assert dispatched.sent == [(run, org)]
    assert (await workspace.detail(run_id))["attempt"] == 2
    assert (await events(workspace, run_id)).count("run.recovered") == 1


async def test_if_the_run_cannot_be_queued_again_it_is_ended_not_lost(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    await die(workspace, runtime_maker, run_id, DyingLLM())

    async def broker_down(*_: Any) -> None:
        raise RuntimeError("the broker is down")

    run, org = ids(workspace, run_id)
    verdict = await recover_run(runtime_maker, org, run, dispatch=broker_down, now=far_future())
    assert verdict is Verdict.FAILED
    failed = await workspace.detail(run_id)
    assert failed["status"] == "failed" and "could not be queued" in failed["error"]


# ---------- the same task delivered twice ----------


async def test_a_task_delivered_twice_while_its_worker_is_alive_does_nothing(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    inside, release = asyncio.Event(), asyncio.Event()

    class Slow:
        calls = 0

        async def complete(self, **_: Any) -> LLMResponse:
            self.calls += 1
            inside.set()
            await release.wait()
            return reply("Done.")

    slow = Slow()
    first = asyncio.create_task(work(workspace, runtime_maker, run_id, slow))
    await asyncio.wait_for(inside.wait(), 5)
    dispatched = Dispatched()
    duplicate = ScriptedLLM(reply("must never be asked"))
    await work(workspace, runtime_maker, run_id, duplicate, dispatch=dispatched)
    assert duplicate.calls == 0 and dispatched.sent == []
    assert (await workspace.detail(run_id))["status"] == "running"  # untouched, not failed

    release.set()
    await first
    assert (await workspace.detail(run_id))["status"] == "succeeded"
    assert slow.calls == 1


async def test_a_task_delivered_again_after_its_worker_died_takes_the_run_over(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    await die(workspace, runtime_maker, run_id, DyingLLM())
    workspace.api.execute(
        "UPDATE agent_runs SET heartbeat_at = now() - interval '10 minutes' WHERE id = :r", r=run_id
    )
    dispatched = Dispatched()
    await work(workspace, runtime_maker, run_id, ScriptedLLM(), dispatch=dispatched)
    assert dispatched.sent == [ids(workspace, run_id)]  # recovered, not failed
    assert (await workspace.detail(run_id))["status"] == "queued"
    await work(workspace, runtime_maker, run_id, ScriptedLLM(reply("Done.")))
    assert (await workspace.detail(run_id))["status"] == "succeeded"


async def test_a_resume_task_delivered_twice_resumes_once(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[CALC])
    llm = ScriptedLLM(call_tools(CALL), reply("The answer is 2."))
    await work(workspace, runtime_maker, run_id, llm)
    await decide(workspace, (await waiting(workspace, run_id))["id"], "approve")
    action = Counted(monkeypatch)
    await asyncio.gather(
        resume(workspace, runtime_maker, llm, run_id),
        resume(workspace, runtime_maker, llm, run_id),
    )
    assert (await workspace.detail(run_id))["status"] == "succeeded"
    assert action.runs == 1


# ---------- a worker that was only stalled ----------


async def test_a_stalled_worker_stops_the_moment_another_has_taken_the_run_over(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await new_run(workspace, tools=[{"tool_key": "utility.calculate"}])
    calculator = Counted(monkeypatch)
    inside, release = asyncio.Event(), asyncio.Event()

    class Stalled:
        """Its host froze inside the model call; the answer arrives only much later."""

        async def complete(self, **_: Any) -> LLMResponse:
            inside.set()
            await release.wait()
            return call_tools(CALL)

    stalled = asyncio.create_task(work(workspace, runtime_maker, run_id, Stalled()))
    await asyncio.wait_for(inside.wait(), 5)
    workspace.api.execute(
        "UPDATE agent_runs SET heartbeat_at = now() - interval '10 minutes' WHERE id = :r", r=run_id
    )
    verdict, _ = await take_over(workspace, runtime_maker, run_id, now=datetime.now(UTC))
    assert verdict is Verdict.REQUEUED
    await work(workspace, runtime_maker, run_id, ScriptedLLM(call_tools(CALL), reply("It is 2.")))
    finished = await workspace.detail(run_id)
    assert finished["status"] == "succeeded" and finished["attempt"] == 2
    assert calculator.runs == 1

    release.set()  # the stalled worker wakes up and tries to carry on
    await asyncio.wait_for(stalled, 5)  # it stops quietly: no exception, no crash
    after = await workspace.detail(run_id)
    assert after["status"] == "succeeded" and after["output"] == finished["output"]
    assert calculator.runs == 1  # and the tool it asked for was not run again
    assert [s["status"] for s in after["steps"]] == [s["status"] for s in finished["steps"]]


async def test_two_workers_cannot_both_start_the_same_tool_call(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    org, run = uuid.UUID(workspace.org_id), uuid.UUID(run_id)
    agent = uuid.UUID(
        str(workspace.api.scalar("SELECT agent_id FROM agent_runs WHERE id = :r", r=run_id))
    )

    def recorder() -> RunRecorder:
        return RunRecorder(runtime_maker, org_id=org, run_id=run, agent_id=agent)

    started = await asyncio.gather(
        *(
            recorder().start_tool_step(
                "1.0", name="utility.calculate", tool_key="utility.calculate"
            )
            for _ in range(6)
        )
    )
    assert sum(1 for s in started if s.existing is None) == 1  # exactly one got to start it
    assert len({s.step_id for s in started}) == 1  # and the rest were pointed at that same step
    count = workspace.api.scalar(
        "SELECT count(*) FROM run_steps WHERE run_id = :r AND call_key = '1.0'", r=run_id
    )
    assert count == 1


# ---------- heartbeats and finding lost workers ----------


async def test_a_working_run_keeps_a_heartbeat_and_is_listed_as_active(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUN_HEARTBEAT_SECONDS", "0.1")
    get_settings.cache_clear()
    run_id = await new_run(workspace)
    inside, release = asyncio.Event(), asyncio.Event()

    class Slow:
        async def complete(self, **_: Any) -> LLMResponse:
            inside.set()
            await release.wait()
            return reply("Done.")

    task = asyncio.create_task(work(workspace, runtime_maker, run_id, Slow()))
    await asyncio.wait_for(inside.wait(), 5)

    def beat() -> Any:
        return workspace.api.scalar("SELECT heartbeat_at FROM agent_runs WHERE id = :r", r=run_id)

    first = beat()
    await asyncio.sleep(0.5)
    assert beat() > first  # it keeps beating while the model call is in flight
    redis = liveness._client(get_settings().redis_url)
    member = f"{workspace.org_id}:{run_id}"
    assert await redis.zscore(liveness.REGISTRY, member) is not None  # and is listed as active

    release.set()
    await task
    assert await redis.zscore(liveness.REGISTRY, member) is None  # listed no longer once finished
    await redis.aclose()


async def test_the_scheduler_sweep_takes_over_only_runs_whose_worker_is_really_gone(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    lost = await new_run(workspace)
    await die(workspace, runtime_maker, lost, DyingLLM())
    alive = await new_run(workspace)
    await die(workspace, runtime_maker, alive, DyingLLM())
    finished = await new_run(workspace)
    await work(workspace, runtime_maker, finished, ScriptedLLM(reply("Hi")))
    workspace.api.execute(
        "UPDATE agent_runs SET heartbeat_at = now() - interval '10 minutes' WHERE id = :r", r=lost
    )

    # All three are listed as active, long ago, as they would be had their workers been killed.
    redis = liveness._client(get_settings().redis_url)
    stale_score = (await redis.time())[0] - 600
    for run_id in (lost, alive, finished):
        await redis.zadd(liveness.REGISTRY, {f"{workspace.org_id}:{run_id}": stale_score})
    await redis.zadd(liveness.REGISTRY, {"not-a-run": stale_score})

    dispatched = Dispatched()
    counts = await recover_stale_runs(runtime_maker, dispatch=dispatched)
    assert counts["requeued"] == 1 and counts["not_stale"] == 1 and counts["gone"] == 1
    assert dispatched.sent == [ids(workspace, lost)]
    assert (await workspace.detail(lost))["status"] == "queued"
    assert (await workspace.detail(alive))["status"] == "running"  # its worker is alive: untouched
    # Taken over or finished entries are dropped from the list; the live one is kept.
    assert await redis.zscore(liveness.REGISTRY, f"{workspace.org_id}:{lost}") is None
    assert await redis.zscore(liveness.REGISTRY, f"{workspace.org_id}:{finished}") is None
    assert await redis.zscore(liveness.REGISTRY, f"{workspace.org_id}:{alive}") is not None
    await redis.zrem(liveness.REGISTRY, f"{workspace.org_id}:{alive}", "not-a-run")
    await redis.aclose()


async def test_the_sweep_does_nothing_when_nothing_is_listed(runtime_maker: Maker) -> None:
    redis = liveness._client(get_settings().redis_url)
    await redis.delete(liveness.REGISTRY)
    await redis.aclose()
    counts = await recover_stale_runs(runtime_maker, dispatch=Dispatched())
    assert sum(counts.values()) == 0


async def test_without_redis_the_heartbeat_still_beats_and_the_sweep_finds_nothing(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # nothing listens here
    get_settings.cache_clear()
    run_id = await new_run(workspace)
    await work(workspace, runtime_maker, run_id, ScriptedLLM(reply("Hi")))  # not broken by it
    assert (await workspace.detail(run_id))["status"] == "succeeded"
    assert workspace.api.scalar("SELECT heartbeat_at FROM agent_runs WHERE id = :r", r=run_id)
    assert sum((await recover_stale_runs(runtime_maker, dispatch=Dispatched())).values()) == 0


# ---------- what the repository now keeps ----------


async def test_claiming_a_run_sets_its_heartbeat_and_keeps_saved_progress(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    assert (
        workspace.api.scalar("SELECT heartbeat_at FROM agent_runs WHERE id = :r", r=run_id) is None
    )
    await die(workspace, runtime_maker, run_id, DyingLLM())
    row = workspace.api.scalar(
        "SELECT checkpoint ->> 'kind' FROM agent_runs WHERE id = :r", r=run_id
    )
    assert row == "progress"  # saved before the first model call
    assert workspace.api.scalar("SELECT heartbeat_at FROM agent_runs WHERE id = :r", r=run_id)


async def test_a_finished_run_keeps_no_saved_state(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await new_run(workspace)
    await work(workspace, runtime_maker, run_id, ScriptedLLM(reply("Hi")))
    assert workspace.api.scalar("SELECT checkpoint FROM agent_runs WHERE id = :r", r=run_id) is None


async def test_resuming_keeps_a_note_of_the_approval_but_not_what_was_decided(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The saved progress says which approval a run was resumed from. What was decided, and the
    exact arguments that were approved, are read from the approval row alone when needed."""
    run_id = await new_run(workspace, tools=[CALC])
    llm = ScriptedLLM(call_tools(("utility_calculate", {"expression": "7 * 191"})), reply("Done"))
    await work(workspace, runtime_maker, run_id, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"], "approve")
    Counted(monkeypatch, die_on={1})
    run, org = ids(workspace, run_id)
    from app.engine.executor import resume_run

    with pytest.raises(WorkerDied):
        await resume_run(run, org, maker=runtime_maker, llm=llm)
    saved = workspace.api.scalar("SELECT checkpoint FROM agent_runs WHERE id = :r", r=run_id)
    assert saved["kind"] == "progress"
    assert set(saved["resume"]) == {"awaiting"}  # no decision, no note, no arguments
    assert saved["resume"]["awaiting"]["approval_id"] == approval["id"]
