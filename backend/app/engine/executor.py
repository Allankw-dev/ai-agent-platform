"""Runs an agent run. Called by the Celery tasks `agents.execute_run` and `agents.resume_run`.

Lifecycle: claim (queued -> running) -> load the agent version and its tools -> run the graph under
a wall-clock timeout -> close the run (succeeded or failed). Closing is conditional on the run
still being 'running', so a cancellation that arrives mid-run is never overwritten.

When an action needs a person, the graph ends early; the loop's state is saved on the run as a
checkpoint and the run waits (status `awaiting_approval`), holding no worker. Once a person has
decided, `resume_run` claims it again (atomically, once) and carries on from the checkpoint. The
time limit applies to each stretch of work; waiting time is not counted.
"""

import asyncio
import uuid
from datetime import timedelta

import structlog
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
    recursion_limit,
    state_from_checkpoint,
)
from app.engine.limits import EffectiveLimits, effective_limits
from app.engine.llm import LLMClient, LLMError, get_llm_client
from app.engine.recorder import RunRecorder
from app.models.agents import AgentVersion
from app.models.enums import ApprovalStatus, RunStatus
from app.repositories import agents as agent_repo
from app.repositories import approvals as approval_repo
from app.repositories import runs as run_repo
from app.tools.base import ToolContext, ToolDefinition
from app.tools.integration_access import DatabaseIntegrationAccess

log = structlog.get_logger()

INTERRUPTED = "The run was interrupted (the worker restarted) and was not resumed."
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
) -> None:
    """Run `run_id` for `org_id`. `maker` and `llm` are injectable for tests."""
    if maker is None:
        async with standalone_sessionmaker() as own:
            await _execute(own, run_id, org_id, llm)
    else:
        await _execute(maker, run_id, org_id, llm)


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
) -> None:
    """Save the loop's state and park the run until a person decides."""
    async with maker() as session:
        await use_tenant(session, org_id=org_id)
        paused = await run_repo.pause(session, run_id, checkpoint_from_state(state))
        if not paused:
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
    output: dict[str, object] | None = None,
    error: str | None = None,
) -> None:
    async with maker() as session:
        await use_tenant(session, org_id=org_id)
        await run_repo.finish(session, run_id, status, output=output, error=error)
        if status is RunStatus.FAILED:
            # A run can fail in the middle of a step (the time limit cuts a model call off, or
            # the code crashed). Never leave that step showing "running" on a finished run.
            await run_repo.fail_running_steps(session, [run_id])
        await session.commit()


async def _execute(
    maker: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    llm: LLMClient | None,
    *,
    resume: bool = False,
) -> None:
    structlog.contextvars.bind_contextvars(run_id=str(run_id), org_id=str(org_id))
    settings = get_settings()
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
                    # A run that is still running is left to its worker; if that worker died, the
                    # orphan check closes the run (and says plainly if an approved action may have
                    # started). It is never resumed twice and never retried.
                    log.info("engine.resume_skipped", status=run.status.value)
                elif run.status is RunStatus.RUNNING:
                    # Redelivered after a worker died mid-run: do not run the agent twice.
                    log.warning("engine.run_interrupted")
                    await run_repo.finish(session, run_id, RunStatus.FAILED, error=INTERRUPTED)
                    await run_repo.fail_running_steps(session, [run_id])
                    await session.commit()
                else:
                    log.info("engine.run_skipped", status=run.status.value)
                return

            version = await agent_repo.get_version_by_id(session, org_id, run.agent_version_id)
            if version is None:
                await run_repo.finish(
                    session, run_id, RunStatus.FAILED, error="The agent version no longer exists."
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
                error=(
                    f"This agent has a cost budget but no price is configured for {model!r}. "
                    "Add it to MODEL_PRICES or remove the budget."
                ),
            )
            return

        try:
            client = llm or get_llm_client(provider)
        except LLMError as exc:
            await _close(maker, org_id, run_id, RunStatus.FAILED, error=str(exc))
            return

        deps = EngineDeps(
            llm=client,
            recorder=RunRecorder(maker, org_id=org_id, run_id=run_id, agent_id=agent_id),
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
            else:
                start = initial_state(message)
            graph = build_graph(deps)
            async with asyncio.timeout(limits.timeout_seconds):
                state: EngineState = await graph.ainvoke(
                    start, {"recursion_limit": recursion_limit(limits)}
                )
        except ValueError as exc:
            if resume_claim is None:
                raise
            log.error("engine.bad_checkpoint", error=str(exc))
            await _close(maker, org_id, run_id, RunStatus.FAILED, error=BAD_CHECKPOINT)
            return
        except TimeoutError:
            await _close(
                maker,
                org_id,
                run_id,
                RunStatus.FAILED,
                error=f"Stopped: the agent hit its {limits.timeout_seconds} second time limit.",
            )
            return

        outcome = Outcome(state.get("outcome") or Outcome.COMPLETED)
        if outcome is Outcome.CANCELLED:
            return  # the API already marked the run cancelled
        if outcome is Outcome.AWAITING_APPROVAL:
            await _pause(maker, org_id, run_id, state)
            return
        text = state.get("final_text", "")
        output: dict[str, object] = {"text": text, "iterations": state.get("iterations", 0)}
        if outcome is Outcome.COMPLETED:
            await _close(maker, org_id, run_id, RunStatus.SUCCEEDED, output=output)
        else:
            await _close(
                maker,
                org_id,
                run_id,
                RunStatus.FAILED,
                output=output if text else None,
                error=failure_message(outcome, state, limits),
            )
    except Exception:
        log.exception("engine.run_crashed")
        try:
            await _close(maker, org_id, run_id, RunStatus.FAILED, error=INTERNAL_ERROR)
        except Exception:
            log.exception("engine.run_close_failed")
    finally:
        structlog.contextvars.unbind_contextvars("run_id", "org_id")
