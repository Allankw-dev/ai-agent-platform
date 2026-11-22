import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent, AgentVersion
from app.models.enums import ApprovalStatus, RunStatus, StepStatus
from app.models.runs import AgentRun, Approval, RunStep

OPEN_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL)


async def get(session: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun | None:
    return await session.scalar(
        select(AgentRun).where(AgentRun.org_id == org_id, AgentRun.id == run_id)
    )


async def get_by_idempotency_key(
    session: AsyncSession, org_id: uuid.UUID, key: str
) -> AgentRun | None:
    return await session.scalar(
        select(AgentRun).where(AgentRun.org_id == org_id, AgentRun.idempotency_key == key)
    )


async def labels(session: AsyncSession, run: AgentRun) -> tuple[int, str]:
    """The run's agent version number and its agent's name (kept even if the agent was deleted)."""
    row = (
        await session.execute(
            select(AgentVersion.version, Agent.name)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(AgentVersion.id == run.agent_version_id)
        )
    ).first()
    return (int(row[0]), str(row[1])) if row else (0, "")


async def list_for_org(
    session: AsyncSession,
    org_id: uuid.UUID,
    limit: int,
    offset: int,
    *,
    agent_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
) -> tuple[list[tuple[AgentRun, int, str]], int]:
    base = select(AgentRun).where(AgentRun.org_id == org_id)
    if agent_id is not None:
        base = base.where(AgentRun.agent_id == agent_id)
    if status is not None:
        base = base.where(AgentRun.status == status)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.add_columns(AgentVersion.version, Agent.name)
        .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [(run, int(number), str(name)) for run, number, name in rows.all()], int(total or 0)


async def list_steps(session: AsyncSession, run_id: uuid.UUID) -> list[RunStep]:
    rows = await session.scalars(
        select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.sequence)
    )
    return list(rows)


async def claim(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Atomically move a queued run to running. False if it was not queued."""
    result = await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == RunStatus.QUEUED)
        .values(status=RunStatus.RUNNING, started_at=datetime.now(UTC))
        .returning(AgentRun.id)
    )
    return result.first() is not None


@dataclass(frozen=True)
class ResumeClaim:
    """A paused run that has just been claimed for resuming, with what it was waiting on."""

    checkpoint: dict[str, Any]
    approval: Approval


async def claim_for_resume(
    session: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID
) -> ResumeClaim | None:
    """Atomically move a run waiting for approval back to running, once its approval is decided.

    Returns None, leaving the run exactly as it is, when there is nothing to resume: the run is
    not waiting, or its approval is still pending (a late or repeated resume task arriving while
    the run waits on a *newer* approval), or it already ended. The row is locked while it is read,
    so two resume tasks can never both claim it.
    """
    run = await session.scalar(
        select(AgentRun).where(AgentRun.org_id == org_id, AgentRun.id == run_id).with_for_update()
    )
    if run is None or run.status is not RunStatus.AWAITING_APPROVAL or not run.checkpoint:
        return None
    awaiting = run.checkpoint.get("awaiting") or {}
    try:
        approval_id = uuid.UUID(str(awaiting.get("approval_id")))
    except ValueError:
        return None
    approval = await session.scalar(
        select(Approval).where(Approval.org_id == org_id, Approval.id == approval_id)
    )
    if approval is None or approval.status not in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
    ):
        return None
    checkpoint = dict(run.checkpoint)
    await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(status=RunStatus.RUNNING, checkpoint=None, last_resumed_at=datetime.now(UTC))
    )
    return ResumeClaim(checkpoint=checkpoint, approval=approval)


async def pause(session: AsyncSession, run_id: uuid.UUID, checkpoint: dict[str, Any]) -> bool:
    """Park a running run until a person decides. False if it is no longer running (cancelled)."""
    result = await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == RunStatus.RUNNING)
        .values(status=RunStatus.AWAITING_APPROVAL, checkpoint=checkpoint)
        .returning(AgentRun.id)
    )
    return result.first() is not None


async def fail_awaiting(session: AsyncSession, run_id: uuid.UUID, error: str) -> bool:
    """End a run that is waiting for approval (the approval expired). False if not waiting."""
    result = await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == RunStatus.AWAITING_APPROVAL)
        .values(
            status=RunStatus.FAILED, error=error, finished_at=datetime.now(UTC), checkpoint=None
        )
        .returning(AgentRun.id)
    )
    return result.first() is not None


async def finish(
    session: AsyncSession,
    run_id: uuid.UUID,
    status: RunStatus,
    *,
    output: dict[str, object] | None = None,
    error: str | None = None,
) -> bool:
    """Close a run that is still running. A run cancelled meanwhile stays cancelled."""
    result = await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == RunStatus.RUNNING)
        .values(status=status, output=output, error=error, finished_at=datetime.now(UTC))
        .returning(AgentRun.id)
    )
    return result.first() is not None


async def cancel(session: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    result = await session.execute(
        update(AgentRun)
        .where(
            AgentRun.org_id == org_id,
            AgentRun.id == run_id,
            AgentRun.status.in_(OPEN_STATUSES),
        )
        .values(status=RunStatus.CANCELLED, finished_at=datetime.now(UTC), checkpoint=None)
        .returning(AgentRun.id)
    )
    return result.first() is not None


ORPHANED_RUN = (
    "The run stopped unexpectedly: the worker running it was shut down or restarted, "
    "so it never finished."
)
ORPHANED_STEP = "The run stopped before this step finished."
UNKNOWN_ACTION_RUN = (
    "The run stopped while an approved action was being carried out, so it is unknown whether "
    "the action happened. It was not retried."
)
UNKNOWN_ACTION_STEP = (
    "The run stopped while this approved action was being carried out. It is unknown whether the "
    "action happened, and it was not retried."
)
NO_DECISION_STEP = "The run ended before anyone decided, so this action was not run."


def _started_approved_action_steps() -> Any:
    """Tool steps that are running although a person approved them: the action may have started."""
    return exists().where(
        Approval.run_step_id == RunStep.id, Approval.status == ApprovalStatus.APPROVED
    )


async def has_started_approved_action(session: AsyncSession, run_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(RunStep.id).where(
            RunStep.run_id == run_id,
            RunStep.status == StepStatus.RUNNING,
            _started_approved_action_steps(),
        )
    )
    return found is not None


async def fail_running_steps(session: AsyncSession, run_ids: list[uuid.UUID]) -> None:
    """Close the half-finished steps of runs that have ended, so none stays unfinished forever.

    A step is still 'running' when its run ended mid-step: the time limit cut a model call off,
    or the worker died. A step that was waiting for a person ('awaiting_approval') when its run
    ended is skipped, because its action never started. An approved action that was already
    running is failed with a plain statement that it is unknown whether it happened (and it is
    never retried). Only steps of the given runs are touched.
    """
    if not run_ids:
        return
    await session.execute(
        update(RunStep)
        .where(
            RunStep.run_id.in_(run_ids),
            RunStep.status == StepStatus.RUNNING,
            _started_approved_action_steps(),
        )
        .values(status=StepStatus.FAILED, error=UNKNOWN_ACTION_STEP, finished_at=func.now())
    )
    await session.execute(
        update(RunStep)
        .where(RunStep.run_id.in_(run_ids), RunStep.status == StepStatus.RUNNING)
        .values(status=StepStatus.FAILED, error=ORPHANED_STEP, finished_at=func.now())
    )
    await end_awaiting_steps(session, run_ids, NO_DECISION_STEP)


async def end_awaiting_steps(session: AsyncSession, run_ids: list[uuid.UUID], error: str) -> None:
    """Skip tool steps still waiting for a decision, for runs that have ended."""
    if not run_ids:
        return
    await session.execute(
        update(RunStep)
        .where(RunStep.run_id.in_(run_ids), RunStep.status == StepStatus.AWAITING_APPROVAL)
        .values(status=StepStatus.SKIPPED, error=error, finished_at=func.now())
    )


async def fail_orphaned(
    session: AsyncSession, org_id: uuid.UUID, *, started_before: datetime
) -> int:
    """Fail RUNNING runs whose current stretch of work began before `started_before`.

    No live run can be that old (every run has a time limit, and the worker has a hard limit
    above it), so the worker that held it is gone. A run resumed after a pause is measured from
    its resume, not from its first start, because waiting for a person is not work. Their
    half-finished steps are failed too. AWAITING_APPROVAL runs are deliberately excluded because
    they are paused for human input, not waiting on a worker. Only the given organization's runs
    are touched, so Row Level Security still applies.
    """
    stretch_start = func.coalesce(AgentRun.last_resumed_at, AgentRun.started_at)
    candidates = [
        row[0]
        for row in await session.execute(
            select(AgentRun.id).where(
                AgentRun.org_id == org_id,
                AgentRun.status == RunStatus.RUNNING,
                stretch_start < started_before,
            )
        )
    ]
    if not candidates:
        return 0
    unknown = [
        run_id for run_id in candidates if await has_started_approved_action(session, run_id)
    ]
    result = await session.execute(
        update(AgentRun)
        .where(AgentRun.id.in_(candidates), AgentRun.status == RunStatus.RUNNING)
        .values(status=RunStatus.FAILED, error=ORPHANED_RUN, finished_at=func.now())
        .returning(AgentRun.id)
    )
    run_ids = [row[0] for row in result]
    if unknown:
        await session.execute(
            update(AgentRun).where(AgentRun.id.in_(unknown)).values(error=UNKNOWN_ACTION_RUN)
        )
    await fail_running_steps(session, run_ids)
    return len(run_ids)


def orphan_cutoff(timeout_ceiling_seconds: int, now: datetime | None = None) -> datetime:
    """Runs that started before this are dead: past the longest allowed run, plus a margin."""
    return (now or datetime.now(UTC)) - timedelta(seconds=timeout_ceiling_seconds + 180)
