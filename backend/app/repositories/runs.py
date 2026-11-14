import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent, AgentVersion
from app.models.enums import RunStatus
from app.models.runs import AgentRun, RunStep

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
        .values(status=RunStatus.CANCELLED, finished_at=datetime.now(UTC))
        .returning(AgentRun.id)
    )
    return result.first() is not None
