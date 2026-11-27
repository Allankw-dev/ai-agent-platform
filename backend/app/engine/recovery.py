"""Taking a run over when the worker that held it has died.

A run is *stale* when it is marked running but its worker's heartbeat stopped. Recovery re-queues it
from its last checkpoint, with one rule above all: **an action is never carried out twice**.

- A model call that was in flight is simply asked again (nothing outside changed).
- A read-only tool that was in flight is run again; its first attempt is closed as interrupted.
- A tool call that had already finished is not run again: the next worker replays its recorded
  result (every call has a key that is unique per run in the database).
- An approved action that had *started* is never retried. Nothing can say whether it happened, so
  the run ends and says exactly that.
- A run is recovered at most RUN_MAX_ATTEMPTS times, so one that keeps killing its worker cannot
  loop forever.

Everything is decided inside the run's own organization, in one transaction that locks the run row,
so two recoverers (two scheduler ticks, or a redelivered task) can never both take it over.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.tenancy import use_tenant
from app.engine import liveness
from app.models.enums import RunEventType, RunStatus, StepStatus
from app.models.runs import AgentRun, RunStep
from app.repositories import run_events
from app.repositories import runs as run_repo
from app.services import audit

log = structlog.get_logger()

Dispatch = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]

INTERRUPTED_STEP = (
    "The worker stopped before this step finished. It had not changed anything outside, so it was "
    "run again."
)
TOO_MANY_ATTEMPTS = (
    "The run was interrupted and recovered {n} times and was stopped, so it cannot loop forever."
)
UNRECOVERABLE = (
    "The run stopped unexpectedly: the worker running it was shut down or restarted, and nothing "
    "had been saved to continue from."
)
NOT_QUEUED = "The run could not be queued to continue after the worker stopped."


class Verdict(StrEnum):
    GONE = "gone"  # not running any more (finished, cancelled, or never existed)
    NOT_STALE = "not_stale"  # its worker is alive
    REQUEUED = "requeued"  # taken over: queued to continue from its last checkpoint
    FAILED = "failed"  # could not be taken over safely, so it was ended with a clear message


def last_sign_of_life(run: AgentRun) -> datetime:
    """When the worker last proved it was alive (older runs without a heartbeat: when it began)."""
    return run.heartbeat_at or run.last_resumed_at or run.started_at or run.created_at


async def recover_run(
    maker: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    dispatch: Dispatch,
    now: datetime | None = None,
) -> Verdict:
    """Take over `run_id` if its worker is gone. Safe to call at any time, by anyone, any number of
    times: only a run that is genuinely stale is touched, and only one caller can take it."""
    settings = get_settings()
    moment = now or datetime.now(UTC)
    async with maker() as session:
        await use_tenant(session, org_id=org_id)
        run = await session.scalar(
            select(AgentRun)
            .where(AgentRun.org_id == org_id, AgentRun.id == run_id)
            .with_for_update()
        )
        if run is None or run.status is not RunStatus.RUNNING:
            return Verdict.GONE
        if last_sign_of_life(run) > moment - timedelta(seconds=settings.run_stale_seconds):
            return Verdict.NOT_STALE

        if await run_repo.has_started_approved_action(session, run_id):
            return await _fail(session, run, run_repo.UNKNOWN_ACTION_RUN)
        if run.attempt >= settings.run_max_attempts:
            return await _fail(session, run, TOO_MANY_ATTEMPTS.format(n=run.attempt))
        if not run.checkpoint or run.checkpoint.get("kind") != "progress":
            return await _fail(session, run, UNRECOVERABLE)

        # Close what was in flight, and free those calls' keys so they can be started again.
        await session.execute(
            update(RunStep)
            .where(RunStep.run_id == run_id, RunStep.status == StepStatus.RUNNING)
            .values(
                status=StepStatus.FAILED,
                error=INTERRUPTED_STEP,
                finished_at=func.now(),
                call_key=None,
            )
        )
        new_attempt = await session.scalar(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == RunStatus.RUNNING,
                AgentRun.attempt == run.attempt,
            )
            .values(status=RunStatus.QUEUED, attempt=run.attempt + 1, heartbeat_at=None)
            .returning(AgentRun.attempt)
        )
        if new_attempt is None:  # pragma: no cover - the row lock makes this impossible
            return Verdict.GONE
        await run_events.emit(session, run_id, RunEventType.RECOVERED, {"attempt": new_attempt})
        await audit.record(
            session,
            org_id=org_id,
            actor_id=None,
            action="run.recovered",
            resource_type="run",
            resource_id=run_id,
            details={"attempt": new_attempt},
        )
        await session.commit()

    try:
        await dispatch(run_id, org_id)
    except Exception:
        log.exception("recovery.dispatch_failed")
        async with maker() as session:
            await use_tenant(session, org_id=org_id)
            failed = await session.scalar(
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == RunStatus.QUEUED,
                    AgentRun.attempt == new_attempt,
                )
                .values(status=RunStatus.FAILED, error=NOT_QUEUED, finished_at=func.now())
                .returning(AgentRun.id)
            )
            if failed is not None:
                await run_events.emit(
                    session, run_id, RunEventType.FINISHED, {"status": RunStatus.FAILED.value}
                )
            await session.commit()
        return Verdict.FAILED
    log.warning("recovery.requeued", run_id=str(run_id), attempt=new_attempt)
    return Verdict.REQUEUED


async def _fail(session: AsyncSession, run: AgentRun, message: str) -> Verdict:
    """End a run that cannot be taken over safely, and say why."""
    await run_repo.finish(session, run.id, RunStatus.FAILED, error=message, attempt=run.attempt)
    await run_repo.fail_running_steps(session, [run.id])
    await audit.record(
        session,
        org_id=run.org_id,
        actor_id=None,
        action="run.recovery_failed",
        resource_type="run",
        resource_id=run.id,
        details={"attempt": run.attempt},
    )
    await session.commit()
    log.warning("recovery.failed", run_id=str(run.id), reason=message[:80])
    return Verdict.FAILED


async def recover_stale_runs(
    maker: async_sessionmaker[AsyncSession], *, dispatch: Dispatch
) -> dict[str, int]:
    """One sweep, run by the scheduler: find runs listed as active whose heartbeat is old, and take
    over the ones whose worker is really gone. Returns how many ended in each verdict."""
    settings = get_settings()
    counts = {verdict.value: 0 for verdict in Verdict}
    for org_id, run_id in await liveness.stale_runs(settings.redis_url, settings.run_stale_seconds):
        try:
            verdict = await recover_run(maker, org_id, run_id, dispatch=dispatch)
        except Exception:
            log.exception("recovery.sweep_failed", run_id=str(run_id))
            continue
        counts[verdict.value] += 1
        if verdict is not Verdict.NOT_STALE:
            # Taken over, ended or gone: no longer this worker's. A new worker lists it afresh.
            await liveness.forget(settings.redis_url, org_id, run_id)
    return counts
