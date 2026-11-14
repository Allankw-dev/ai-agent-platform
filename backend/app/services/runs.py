import asyncio
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.config import get_settings
from app.core.errors import ApiError
from app.models.enums import AgentStatus, LLMProvider, RunStatus, RunTrigger
from app.models.runs import AgentRun, RunStep
from app.repositories import agents as agent_repo
from app.repositories import runs as run_repo
from app.schemas.run import RunCreate, RunDetail, RunRead, RunStepRead
from app.services import audit

log = structlog.get_logger()

# Hands a queued run to a worker: (run_id, org_id). Replaceable in tests.
Dispatcher = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]

RUNNABLE = (AgentStatus.DRAFT, AgentStatus.ACTIVE)
MAX_IDEMPOTENCY_KEY = 200


async def celery_dispatcher(run_id: uuid.UUID, org_id: uuid.UUID) -> None:
    from app.workers.tasks import execute_run_task

    # `.delay` talks to the broker synchronously, so keep it off the event loop.
    await asyncio.to_thread(execute_run_task.delay, str(run_id), str(org_id))


def provider_ready(provider: LLMProvider) -> bool:
    """Fail fast at the API instead of queueing a run that can only fail in the worker."""
    settings = get_settings()
    if provider.value not in settings.enabled_llm_providers:
        return False
    if provider is LLMProvider.GEMINI:
        return settings.gemini_api_key is not None
    return False


def run_read(run: AgentRun, version_number: int, agent_name: str) -> RunRead:
    return RunRead(
        id=run.id,
        agent_id=run.agent_id,
        agent_name=agent_name,
        agent_version_id=run.agent_version_id,
        agent_version=version_number,
        status=run.status,
        trigger=run.trigger,
        input=run.input,
        output=run.output,
        error=run.error,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cost_usd=float(run.cost_usd),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def step_read(step: RunStep) -> RunStepRead:
    return RunStepRead(
        id=step.id,
        sequence=step.sequence,
        step_type=step.step_type,
        status=step.status,
        name=step.name,
        tool_key=step.tool_key,
        input=step.input,
        output=step.output,
        error=step.error,
        input_tokens=step.input_tokens,
        output_tokens=step.output_tokens,
        started_at=step.started_at,
        finished_at=step.finished_at,
    )


async def get_run_detail(session: AsyncSession, ctx: OrgContext, run_id: uuid.UUID) -> RunDetail:
    run = await run_repo.get(session, ctx.org_id, run_id)
    if run is None:
        raise ApiError(404, "run_not_found", "Run not found.")
    number, agent_name = await run_repo.labels(session, run)
    steps = await run_repo.list_steps(session, run.id)
    return RunDetail(
        **run_read(run, number, agent_name).model_dump(), steps=[step_read(s) for s in steps]
    )


async def create_run(
    session: AsyncSession,
    ctx: OrgContext,
    agent_id: uuid.UUID,
    body: RunCreate,
    idempotency_key: str | None,
    dispatch: Dispatcher,
) -> tuple[RunRead, bool]:
    """Queue a run of the agent's current version. Returns (run, created)."""
    if idempotency_key is not None and not (0 < len(idempotency_key) <= MAX_IDEMPOTENCY_KEY):
        raise ApiError(422, "invalid_idempotency_key", "The Idempotency-Key header is invalid.")

    if idempotency_key:
        existing = await run_repo.get_by_idempotency_key(session, ctx.org_id, idempotency_key)
        if existing is not None:
            return await _existing(session, existing, agent_id), False

    agent = await agent_repo.get(session, ctx.org_id, agent_id)
    if agent is None:
        raise ApiError(404, "agent_not_found", "Agent not found.")
    if agent.status not in RUNNABLE or agent.current_version_id is None:
        raise ApiError(409, "agent_not_runnable", "Only draft or active agents can be run.")
    version = await agent_repo.get_version_by_id(session, ctx.org_id, agent.current_version_id)
    if version is None:  # pragma: no cover - the foreign key makes this impossible
        raise ApiError(409, "agent_not_runnable", "The agent has no version to run.")
    if not provider_ready(version.provider):
        raise ApiError(
            503,
            "ai_not_configured",
            f"The {version.provider.value} provider is not configured on this platform.",
        )

    run = AgentRun(
        org_id=ctx.org_id,
        agent_id=agent.id,
        agent_version_id=agent.current_version_id,
        status=RunStatus.QUEUED,
        trigger=RunTrigger(body.trigger),
        input={"message": body.message},
        idempotency_key=idempotency_key or None,
        created_by_id=ctx.user.id,
    )
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError:
        # Two requests with the same key raced; the other one won.
        existing = (
            await run_repo.get_by_idempotency_key(session, ctx.org_id, idempotency_key)
            if idempotency_key
            else None
        )
        if existing is None:
            raise
        return await _existing(session, existing, agent_id), False

    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="run.created",
        resource_type="run",
        resource_id=run.id,
        details={"agent_id": str(agent.id), "trigger": body.trigger},
    )
    await session.commit()  # the worker must be able to see the run before it is dispatched

    try:
        await dispatch(run.id, ctx.org_id)
    except Exception as exc:
        log.exception("runs.dispatch_failed", run_id=str(run.id))
        # Free the idempotency key so the caller can simply retry.
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id, AgentRun.status == RunStatus.QUEUED)
            .values(
                status=RunStatus.FAILED, error="The run could not be queued.", idempotency_key=None
            )
        )
        await session.commit()
        raise ApiError(503, "queue_unavailable", "The run could not be queued. Try again.") from exc

    number, agent_name = await run_repo.labels(session, run)
    return run_read(run, number, agent_name), True


async def _existing(session: AsyncSession, run: AgentRun, agent_id: uuid.UUID) -> RunRead:
    if run.agent_id != agent_id:
        raise ApiError(
            409, "idempotency_key_reused", "That Idempotency-Key was used for a different agent."
        )
    number, agent_name = await run_repo.labels(session, run)
    return run_read(run, number, agent_name)


async def cancel_run(session: AsyncSession, ctx: OrgContext, run_id: uuid.UUID) -> RunRead:
    run = await run_repo.get(session, ctx.org_id, run_id)
    if run is None:
        raise ApiError(404, "run_not_found", "Run not found.")
    if not await run_repo.cancel(session, ctx.org_id, run_id):
        raise ApiError(409, "run_not_cancellable", "This run has already finished.")
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="run.cancelled",
        resource_type="run",
        resource_id=run_id,
    )
    await session.commit()
    await session.refresh(run)
    number, agent_name = await run_repo.labels(session, run)
    return run_read(run, number, agent_name)
