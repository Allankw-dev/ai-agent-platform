import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent, AgentTool, AgentVersion, Tool
from app.models.enums import AgentStatus


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get(
    session: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID, *, lock: bool = False
) -> Agent | None:
    """A live (not deleted) agent. `lock` serializes concurrent edits of the same agent."""
    statement = select(Agent).where(
        Agent.org_id == org_id, Agent.id == agent_id, Agent.deleted_at.is_(None)
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def list_with_current_version(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    status: AgentStatus | None,
    query: str | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Agent, AgentVersion | None]], int]:
    base = select(Agent).where(Agent.org_id == org_id, Agent.deleted_at.is_(None))
    if status is not None:
        base = base.where(Agent.status == status)
    if query:
        base = base.where(Agent.name.ilike(f"%{_escape_like(query)}%", escape="\\"))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    statement = (
        base.add_columns(AgentVersion)
        .outerjoin(AgentVersion, AgentVersion.id == Agent.current_version_id)
        .order_by(Agent.updated_at.desc(), Agent.name)
        .limit(limit)
        .offset(offset)
    )
    rows = await session.execute(statement)
    return [(agent, version) for agent, version in rows.all()], int(total or 0)


async def get_version(
    session: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID, number: int
) -> AgentVersion | None:
    return await session.scalar(
        select(AgentVersion).where(
            AgentVersion.org_id == org_id,
            AgentVersion.agent_id == agent_id,
            AgentVersion.version == number,
        )
    )


async def get_version_by_id(
    session: AsyncSession, org_id: uuid.UUID, version_id: uuid.UUID
) -> AgentVersion | None:
    return await session.scalar(
        select(AgentVersion).where(AgentVersion.org_id == org_id, AgentVersion.id == version_id)
    )


async def list_versions(
    session: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[AgentVersion], int]:
    base = select(AgentVersion).where(
        AgentVersion.org_id == org_id, AgentVersion.agent_id == agent_id
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.scalars(
        base.order_by(AgentVersion.version.desc()).limit(limit).offset(offset)
    )
    return list(rows), int(total or 0)


async def next_version_number(session: AsyncSession, agent_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent_id)
    )
    return int(current or 0) + 1


async def assignments_for(
    session: AsyncSession, version_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[AgentTool, Tool]]]:
    if not version_ids:
        return {}
    rows = await session.execute(
        select(AgentTool, Tool)
        .join(Tool, Tool.id == AgentTool.tool_id)
        .where(AgentTool.agent_version_id.in_(version_ids))
        .order_by(Tool.key)
    )
    grouped: dict[uuid.UUID, list[tuple[AgentTool, Tool]]] = {vid: [] for vid in version_ids}
    for assignment, tool in rows.all():
        grouped[assignment.agent_version_id].append((assignment, tool))
    return grouped
