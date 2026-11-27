"""Runs an agent run. Called by the Celery tasks `agents.execute_run` and `agents.resume_run`.

Lifecycle: claim (queued -> running) -> load the agent version and its tools -> run the graph under
a wall-clock timeout -> close the run (succeeded or failed). Closing is conditional on the run
still being 'running', so a cancellation that arrives mid-run is never overwritten.

While it works, a run keeps a heartbeat and saves its progress after every model call and tool
call. If its worker dies, the scheduler re-queues it from that progress (see engine/recovery.py);
every write a worker makes is conditional on its own attempt number, so a worker that was only
stalled stops the moment another has taken over, and no tool call is ever carried out twice.

When an action needs a person, the graph ends early; the loop's state is saved on the run as a
checkpoint and the run waits (status `awaiting_approval`), holding no worker. Once a person has
decided, `resume_run` claims it again (atomically, once) and carries on from the checkpoint. The
time limit applies to each stretch of work; waiting time is not counted.
"""

import asyncio
import uuid
from datetime import timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import standalone_sessionmaker
from app.db.tenancy import use_tenant
from app.engine.graph import (
    EngineConfig,
    EngineDeps,
    EngineState,
    Outcome,
    build_graph,
    checkpoint_from_state,
    initial_state,
    progress_checkpoint,
    recursion_limit,
    state_from_checkpoint,
    state_from_progress,
)
from app.engine.limits import EffectiveLimits, effective_limits
from app.engine.liveness import Heartbeat
from app.engine.llm import LLMClient, LLMError, get_llm_client
from app.engine.recorder import RunRecorder, RunSuperseded
from app.engine.recovery import Dispatch, Verdict, recover_run
from app.models.agents import AgentVersion
from app.models.enums import ApprovalStatus, RunStatus
from app.models.runs import Approval
from app.repositories import agents as agent_repo
from app.repositories import approvals as approval_repo
from app.repositories import runs as run_repo
from app.tools.base import ToolContext, ToolDefinition
from app.tools.integration_access import DatabaseIntegrationAccess

log = structlog.get_logger()

BAD_CHECKPOINT = "The saved state of this run could not be used, so it could not continue."
INTERNAL_ERROR = "An internal error stopped this run."


def system_prompt(version: AgentVersion) -> str:
    if version.objectives:
        return f"{version.system_instructions}\n\nObjectives:\n{version.objectives}"
    return version.system_instructions


def failure_message(outcome: Outcome, state: EngineState, limits: EffectiveLimits) -> str:
    match outcome:
        case Outcome.TRUNCATED:
            return (
                "The model's reply was cut off. Raise max_output_tokens in the agent's model "
                "settings."
            )
        case Outcome.REFUSED:
            return "The model declined to respond."
        case Outcome.EMPTY:
            return "The model returned an empty reply."
        case Outcome.LLM_ERROR:
            return state.get("error") or "The AI provider returned an error."
        case Outcome.ITERATION_LIMIT:
            return f"Stopped: the agent reached its limit of {limits.max_iterations} model calls."
        case Outcome.TOOL_CALL_LIMIT:
            return f"Stopped: the agent reached its limit of {limits.max_tool_calls} tool calls."
        case Outcome.TOKEN_LIMIT:
            return f"Stopped: the agent reached its limit of {limits.max_total_tokens} tokens."
        case Outcome.COST_LIMIT:
            return f"Stopped: the agent reached its cost budget of ${limits.cost_budget_usd}."
        case _:
            return INTERNAL_ERROR


async def execute_run(
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    maker: async_sessionmaker[AsyncSession] | None = None,
    llm: LLMClient | None = None,
    dispatch: Dispatch | None = None,
) -> None:
    """Run `run_id` for `org_id`. `maker`, `llm` and `dispatch` are injectable for tests."""
    if maker is None:
        async with standalone_sessionmaker() as own:
            await _execute(own, run_id, org_id, llm, dispatch=dispatch)
    else:
        await _execute(maker, run_id, org_id, llm, dispatch=dispatch)


async def resume_run(
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    maker: async_sessionmaker[AsyncSession] | None = None,
    llm: LLMClient | None = None,
) -> None:
    """Continue a run that was waiting for a person, now that they have decided.

    Harmless to call more than once, or when there is nothing to resume: only one call can claim
    the run, and the rest return without doing anything.
    """
    if maker is None:
        async with standalone_sessionmaker() as own:
            await _execute(own, run_id, org_id, llm, resume=True)
    else:
        await _execute(maker, run_id, org_id, llm, resume=True)


async def _pause(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    state: EngineState,
    attempt: int,
) -> None:
    """Save the loop's state and park the run until a person decides."""
    async with maker() as session:
        await use_tenant(session, org_id=org_id)
        paused = await run_repo.pause(
            session, run_id, checkpoint_from_state(state), attempt=attempt
        )
        if not paused and await run_repo.is_held_by(session, run_id, attempt):
            # The run was cancelled while the action was being proposed: nobody should be asked.
            await approval_repo.cancel_for_run(session, org_id, run_id)
            await run_repo.end_awaiting_steps(session, [run_id], run_repo.NO_DECISION_STEP)
        await session.commit()


async def _close(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    status: RunStatus,
    *,
    attempt: int | None = None,
    output: dict[str, object] | None = None,
    error: str | None = None,
) -> None:
    async with maker() as session:
        await use_tenant(session, org_id=org_id)
        closed = await run_repo.finish(
            session, run_id, status, output=output, error=error, attempt=attempt
        )
        if closed and status is RunStatus.FAILED:
            # A run can fail in the middle of a step (the time limit cuts a model call off, or
            # the code crashed). Never leave that step showing "running" on a finished run. Only
            # when this worker really closed the run: if another took it over, its steps are its.
            await run_repo.fail_running_steps(session, [run_id])
        await session.commit()


async def _resume_data(
    maker: async_sessionmaker[AsyncSession], org_id: uuid.UUID, state: EngineState
) -> EngineState:
    """Fill in the decision of a run recovered right after it was resumed.

    The progress checkpoint only notes *which* approval the run was resumed from. What was decided,
    the note, and above all the exact arguments that were approved are read from the approval row,
    the one place they live.
    """
    marker = state.get("resume") or {}
    awaiting = marker.get("awaiting") or state.get("awaiting") or {}
    try:
        approval_id = uuid.UUID(str(awaiting.get("approval_id")))
    except ValueError as exc:
        raise ValueError("The saved state of this run points at no approval.") from exc
    async with maker() as session:
        await use_tenant(session, org_id=org_id)
        approval = await session.scalar(
            select(Approval).where(Approval.org_id == org_id, Approval.id == approval_id)
        )
    if approval is None or approval.status not in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
    ):
        raise ValueError("The approval this run was resumed from is not decided.")
    state["resume"] = {
        "awaiting": awaiting,
        "decision": "approved" if approval.status is ApprovalStatus.APPROVED else "rejected",
        "note": approval.decision_note,
        "arguments": approval.proposed_input,
    }
    return state


async def _execute(
    maker: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    llm: LLMClient | None,
    *,
    resume: bool = False,
    dispatch: Dispatch | None = None,
) -> None:
    structlog.contextvars.bind_contextvars(run_id=str(run_id), org_id=str(org_id))
    settings = get_settings()
    attempt = 1
    try:
        async with maker() as session:
            await use_tenant(session, org_id=org_id)
            resume_claim = None
            if resume:
                resume_claim = await run_repo.claim_for_resume(session, org_id, run_id)
                claimed = resume_claim is not None
            else:
                claimed = await run_repo.claim(session, run_id)
            await session.commit()
            run = await run_repo.get(session, org_id, run_id)
            if run is None:
                log.warning("engine.run_missing")
                return
            if not claimed:
                if resume:
                    # Nothing to resume: a repeated task, or the run already ended or moved on.
                    # A run that is still running is left to its worker (or to recovery, if that
                    # worker died). It is never resumed twice.
                    log.info("engine.resume_skipped", status=run.status.value)
                elif run.status is RunStatus.RUNNING:
                    # Delivered again while the run is running. If its worker is alive this is a
                    # duplicate and nothing is done. If its heartbeat stopped, the worker died and
                    # this delivery takes the run over instead of failing it.
                    if dispatch is None:
                        from app.services.runs import celery_dispatcher

                        dispatch = celery_dispatcher
                    verdict = await recover_run(maker, org_id, run_id, dispatch=dispatch)
                    log.warning("engine.duplicate_delivery", verdict=verdict.value)
                    if verdict is Verdict.REQUEUED:
                        return
                else:
                    log.info("engine.run_skipped", status=run.status.value)
                return

            attempt = run.attempt
            saved_progress = run.checkpoint if not resume else None
            version = await agent_repo.get_version_by_id(session, org_id, run.agent_version_id)
            if version is None:
                await run_repo.finish(
                    session,
                    run_id,
                    RunStatus.FAILED,
                    error="The agent version no longer exists.",
                    attempt=attempt,
                )
                await session.commit()
                return
            assignments = (await agent_repo.assignments_for(session, [version.id])).get(
                version.id, []
            )
            tools = [
                ToolDefinition(
                    id=tool.id,
                    key=tool.key,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    is_sensitive=tool.is_sensitive,
                    timeout_seconds=tool.timeout_seconds,
                    requires_approval=assignment.requires_approval,
                    config=assignment.config,
                )
                for assignment, tool in assignments
            ]
            message = str(run.input.get("message", ""))
            agent_id = run.agent_id
            limits = effective_limits(version.limits, settings)
            max_output_tokens = version.model_params.get("max_output_tokens")
            prompt = system_prompt(version)
            provider, model = version.provider, version.model

        if limits.cost_budget_micro_usd is not None and model not in settings.model_prices:
            await _close(
                maker,
                org_id,
                run_id,
                RunStatus.FAILED,
                attempt=attempt,
                error=(
                    f"This agent has a cost budget but no price is configured for {model!r}. "
                    "Add it to MODEL_PRICES or remove the budget."
                ),
            )
            return

        try:
            client = llm or get_llm_client(provider)
        except LLMError as exc:
            await _close(maker, org_id, run_id, RunStatus.FAILED, attempt=attempt, error=str(exc))
            return

        recorder = RunRecorder(
            maker, org_id=org_id, run_id=run_id, agent_id=agent_id, attempt=attempt
        )
        deps = EngineDeps(
            llm=client,
            recorder=recorder,
            tools=tools,
            config=EngineConfig(
                model=model,
                system=prompt,
                max_output_tokens=max_output_tokens,
                limits=limits,
                prices=settings.model_prices,
                approval_ttl=timedelta(hours=settings.approval_expiry_hours),
            ),
            context=ToolContext(
                org_id=org_id,
                agent_id=agent_id,
                run_id=run_id,
                integrations=DatabaseIntegrationAccess(maker, org_id),
            ),
        )

        try:
            start: EngineState
            if resume_claim is not None:
                start = state_from_checkpoint(
                    resume_claim.checkpoint,
                    decision=(
                        "approved"
                        if resume_claim.approval.status is ApprovalStatus.APPROVED
                        else "rejected"
                    ),
                    note=resume_claim.approval.decision_note,
                    arguments=resume_claim.approval.proposed_input,
                )
            elif saved_progress:
                # A recovered run: carry on from where the lost worker last saved its progress.
                start = state_from_progress(saved_progress)
                if start.get("resume"):
                    start = await _resume_data(maker, org_id, start)
            else:
                start = initial_state(message)
                # Saved before the first model call, so even a worker lost during it can be
                # replaced by one that starts from the same place.
                await recorder.save_progress(progress_checkpoint(start))
            graph = build_graph(deps)
            async with (
                Heartbeat(
                    recorder,
                    org_id=org_id,
                    run_id=run_id,
                    interval_seconds=settings.run_heartbeat_seconds,
                    redis_url=settings.redis_url,
                ),
                asyncio.timeout(limits.timeout_seconds),
            ):
                state: EngineState = await graph.ainvoke(
                    start, {"recursion_limit": recursion_limit(limits)}
                )
        except ValueError as exc:
            if resume_claim is None and not saved_progress:
                raise
            log.error("engine.bad_checkpoint", error=str(exc))
            await _close(
                maker, org_id, run_id, RunStatus.FAILED, attempt=attempt, error=BAD_CHECKPOINT
            )
            return
        except TimeoutError:
            await _close(
                maker,
                org_id,
                run_id,
                RunStatus.FAILED,
                attempt=attempt,
                error=f"Stopped: the agent hit its {limits.timeout_seconds} second time limit.",
            )
            return

        outcome = Outcome(state.get("outcome") or Outcome.COMPLETED)
        if outcome is Outcome.CANCELLED:
            return  # the API already marked the run cancelled
        if outcome is Outcome.AWAITING_APPROVAL:
            await _pause(maker, org_id, run_id, state, attempt)
            return
        text = state.get("final_text", "")
        output: dict[str, object] = {"text": text, "iterations": state.get("iterations", 0)}
        if outcome is Outcome.COMPLETED:
            await _close(maker, org_id, run_id, RunStatus.SUCCEEDED, attempt=attempt, output=output)
        else:
            await _close(
                maker,
                org_id,
                run_id,
                RunStatus.FAILED,
                attempt=attempt,
                output=output if text else None,
                error=failure_message(outcome, state, limits),
            )
    except RunSuperseded:
        # Another worker has taken this run over: it is theirs now, so leave it exactly as it is.
        log.warning("engine.superseded", attempt=attempt)
    except Exception:
        log.exception("engine.run_crashed")
        try:
            await _close(
                maker, org_id, run_id, RunStatus.FAILED, attempt=attempt, error=INTERNAL_ERROR
            )
        except Exception:
            log.exception("engine.run_close_failed")
    finally:
        structlog.contextvars.unbind_contextvars("run_id", "org_id")
