import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.config import get_settings
from app.core.errors import ApiError
from app.models.agents import Agent, AgentTool, AgentVersion
from app.models.enums import AgentStatus
from app.repositories import agents as agent_repo
from app.repositories import tools as tool_repo
from app.schemas.agent import (
    AgentConfig,
    AgentCreate,
    AgentListItem,
    AgentRead,
    AgentUpdate,
    ToolAssignmentRead,
    VersionRead,
    VersionSummary,
)
from app.services import audit


def _not_found() -> ApiError:
    return ApiError(404, "agent_not_found", "Agent not found.")


def _name_taken() -> ApiError:
    return ApiError(409, "agent_name_taken", "An agent with that name already exists.")


# ---------- validation of a configuration against the platform's rules ----------


async def _validate_config(session: AsyncSession, config: AgentConfig) -> dict[str, bool]:
    """Checks a configuration and returns {tool_key: effective requires_approval}."""
    settings = get_settings()

    if config.provider.value not in settings.enabled_llm_providers:
        raise ApiError(
            422,
            "provider_not_enabled",
            f"The provider '{config.provider.value}' is not enabled on this server.",
        )

    limits = config.limits
    ceilings: list[tuple[str, float | int | None, float | int]] = [
        ("max_iterations", limits.max_iterations, settings.agent_max_iterations_ceiling),
        ("timeout_seconds", limits.timeout_seconds, settings.agent_timeout_ceiling_seconds),
        ("max_total_tokens", limits.max_total_tokens, settings.agent_token_budget_ceiling),
        ("cost_budget_usd", limits.cost_budget_usd, settings.agent_cost_budget_ceiling_usd),
    ]
    for name, value, ceiling in ceilings:
        if value is not None and value > ceiling:
            raise ApiError(
                422,
                "limit_exceeds_platform_maximum",
                f"limits.{name} cannot exceed {ceiling} on this platform.",
            )

    keys = [tool.tool_key for tool in config.tools]
    catalog = await tool_repo.by_keys(session, keys)
    unknown = [key for key in keys if key not in catalog]
    if unknown:
        raise ApiError(422, "unknown_tool", f"Unknown tool: {', '.join(sorted(unknown))}.")

    # A sensitive tool can never be switched to "run without approval".
    return {
        tool.tool_key: tool.requires_approval or catalog[tool.tool_key].is_sensitive
        for tool in config.tools
    }


async def _insert_version(
    session: AsyncSession,
    ctx: OrgContext,
    agent: Agent,
    config: AgentConfig,
    approvals: dict[str, bool],
    change_note: str | None,
) -> AgentVersion:
    catalog = await tool_repo.by_keys(session, [tool.tool_key for tool in config.tools])
    version = AgentVersion(
        org_id=ctx.org_id,
        agent_id=agent.id,
        version=await agent_repo.next_version_number(session, agent.id),
        provider=config.provider,
        model=config.model,
        system_instructions=config.system_instructions,
        objectives=config.objectives,
        model_params=config.model_params.model_dump(exclude_none=True),
        memory_config=config.memory_config.model_dump(),
        limits=config.limits.model_dump(exclude_none=True),
        change_note=change_note,
        created_by_id=ctx.user.id,
    )
    session.add(version)
    await session.flush()
    for tool in config.tools:
        session.add(
            AgentTool(
                org_id=ctx.org_id,
                agent_version_id=version.id,
                tool_id=catalog[tool.tool_key].id,
                requires_approval=approvals[tool.tool_key],
                config=tool.config,
            )
        )
    await session.flush()
    return version


# ---------- reading ----------


async def _version_read(session: AsyncSession, version: AgentVersion) -> VersionRead:
    assigned = (await agent_repo.assignments_for(session, [version.id]))[version.id]
    return VersionRead(
        id=version.id,
        version=version.version,
        provider=version.provider,
        model=version.model,
        change_note=version.change_note,
        created_by_id=version.created_by_id,
        created_at=version.created_at,
        system_instructions=version.system_instructions,
        objectives=version.objectives,
        model_params=version.model_params,
        memory_config=version.memory_config,
        limits=version.limits,
        tools=[
            ToolAssignmentRead(
                tool_key=tool.key,
                name=tool.name,
                description=tool.description,
                is_sensitive=tool.is_sensitive,
                requires_approval=assignment.requires_approval,
                config=assignment.config,
            )
            for assignment, tool in assigned
        ],
    )


async def agent_detail(session: AsyncSession, org_id: uuid.UUID, agent: Agent) -> AgentRead:
    # updated_at is maintained by the database, so after an UPDATE it must be re-read explicitly
    # (an async session cannot lazy-load it).
    await session.refresh(agent)
    current = None
    if agent.current_version_id is not None:
        version = await agent_repo.get_version_by_id(session, org_id, agent.current_version_id)
        if version is not None:
            current = await _version_read(session, version)
    return AgentRead(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        status=agent.status.value,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        current_version=current,
    )


async def get_agent(session: AsyncSession, ctx: OrgContext, agent_id: uuid.UUID) -> AgentRead:
    agent = await agent_repo.get(session, ctx.org_id, agent_id)
    if agent is None:
        raise _not_found()
    return await agent_detail(session, ctx.org_id, agent)


async def list_agents(
    session: AsyncSession,
    ctx: OrgContext,
    *,
    status: AgentStatus | None,
    query: str | None,
    limit: int,
    offset: int,
) -> tuple[list[AgentListItem], int]:
    rows, total = await agent_repo.list_with_current_version(
        session, ctx.org_id, status=status, query=query, limit=limit, offset=offset
    )
    items = [
        AgentListItem(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            status=agent.status.value,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
            current_version=VersionSummary.model_validate(version) if version else None,
        )
        for agent, version in rows
    ]
    return items, total


async def get_version(
    session: AsyncSession, ctx: OrgContext, agent_id: uuid.UUID, number: int
) -> VersionRead:
    if await agent_repo.get(session, ctx.org_id, agent_id) is None:
        raise _not_found()
    version = await agent_repo.get_version(session, ctx.org_id, agent_id, number)
    if version is None:
        raise ApiError(404, "version_not_found", "Version not found.")
    return await _version_read(session, version)


async def list_versions(
    session: AsyncSession, ctx: OrgContext, agent_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[VersionSummary], int]:
    if await agent_repo.get(session, ctx.org_id, agent_id) is None:
        raise _not_found()
    rows, total = await agent_repo.list_versions(session, ctx.org_id, agent_id, limit, offset)
    return [VersionSummary.model_validate(row) for row in rows], total


# ---------- changing ----------


async def _add_agent(
    session: AsyncSession, ctx: OrgContext, name: str, description: str | None
) -> Agent:
    agent = Agent(
        org_id=ctx.org_id,
        name=name,
        description=description,
        status=AgentStatus.DRAFT,
        created_by_id=ctx.user.id,
    )
    try:
        async with session.begin_nested():
            session.add(agent)
            await session.flush()
    except IntegrityError as exc:
        raise _name_taken() from exc
    return agent


async def create_agent(session: AsyncSession, ctx: OrgContext, body: AgentCreate) -> AgentRead:
    approvals = await _validate_config(session, body.config)
    agent = await _add_agent(session, ctx, body.name, body.description)
    version = await _insert_version(session, ctx, agent, body.config, approvals, "Initial version")
    agent.current_version_id = version.id
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="agent.created",
        resource_type="agent",
        resource_id=agent.id,
        details={"name": agent.name, "provider": version.provider.value, "model": version.model},
    )
    await session.commit()
    return await agent_detail(session, ctx.org_id, agent)


async def update_agent(
    session: AsyncSession, ctx: OrgContext, agent_id: uuid.UUID, body: AgentUpdate
) -> AgentRead:
    agent = await agent_repo.get(session, ctx.org_id, agent_id, lock=True)
    if agent is None:
        raise _not_found()

    changes: dict[str, Any] = {}
    if "name" in body.model_fields_set and body.name is not None and body.name != agent.name:
        changes["name"] = {"from": agent.name, "to": body.name}
        agent.name = body.name
    if "description" in body.model_fields_set and body.description != agent.description:
        agent.description = body.description
        changes["description"] = "updated"
    if body.status is not None and body.status != agent.status.value:
        changes["status"] = {"from": agent.status.value, "to": body.status}
        agent.status = AgentStatus(body.status)

    if changes:
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as exc:
            raise _name_taken() from exc
        action = "agent.updated"
        if set(changes) == {"status"}:
            action = "agent.enabled" if agent.status is AgentStatus.ACTIVE else "agent.disabled"
        await audit.record(
            session,
            org_id=ctx.org_id,
            actor_id=ctx.user.id,
            action=action,
            resource_type="agent",
            resource_id=agent.id,
            details=changes,
        )
    await session.commit()
    return await agent_detail(session, ctx.org_id, agent)


async def create_version(
    session: AsyncSession,
    ctx: OrgContext,
    agent_id: uuid.UUID,
    config: AgentConfig,
    change_note: str | None,
) -> VersionRead:
    # Locking the agent row makes concurrent edits queue up, so version numbers never collide.
    agent = await agent_repo.get(session, ctx.org_id, agent_id, lock=True)
    if agent is None:
        raise _not_found()
    approvals = await _validate_config(session, config)
    version = await _insert_version(session, ctx, agent, config, approvals, change_note)
    previous = agent.current_version_id
    agent.current_version_id = version.id
    agent.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="agent.version_created",
        resource_type="agent",
        resource_id=agent.id,
        details={
            "version": version.version,
            "previous_version_id": str(previous) if previous else None,
            "model": version.model,
        },
    )
    await session.commit()
    return await _version_read(session, version)


async def rollback(
    session: AsyncSession, ctx: OrgContext, agent_id: uuid.UUID, number: int
) -> AgentRead:
    """Point the agent at an earlier version. Versions are never modified or deleted."""
    agent = await agent_repo.get(session, ctx.org_id, agent_id, lock=True)
    if agent is None:
        raise _not_found()
    target = await agent_repo.get_version(session, ctx.org_id, agent_id, number)
    if target is None:
        raise ApiError(404, "version_not_found", "Version not found.")
    if agent.current_version_id == target.id:
        raise ApiError(409, "already_current", "That version is already the current one.")
    previous = agent.current_version_id
    agent.current_version_id = target.id
    agent.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="agent.rolled_back",
        resource_type="agent",
        resource_id=agent.id,
        details={
            "to_version": target.version,
            "from_version_id": str(previous) if previous else None,
        },
    )
    await session.commit()
    return await agent_detail(session, ctx.org_id, agent)


async def duplicate(
    session: AsyncSession, ctx: OrgContext, agent_id: uuid.UUID, name: str | None
) -> AgentRead:
    source = await agent_repo.get(session, ctx.org_id, agent_id)
    if source is None or source.current_version_id is None:
        raise _not_found()
    version = await agent_repo.get_version_by_id(session, ctx.org_id, source.current_version_id)
    if version is None:  # pragma: no cover - the FK guarantees it exists
        raise _not_found()
    assigned = (await agent_repo.assignments_for(session, [version.id]))[version.id]

    config = AgentConfig.model_validate(
        {
            "provider": version.provider,
            "model": version.model,
            "system_instructions": version.system_instructions,
            "objectives": version.objectives,
            "model_params": version.model_params,
            "memory_config": version.memory_config,
            "limits": version.limits,
            "tools": [
                {
                    "tool_key": tool.key,
                    "requires_approval": assignment.requires_approval,
                    "config": assignment.config,
                }
                for assignment, tool in assigned
            ],
        }
    )
    approvals = await _validate_config(session, config)

    candidates = (
        [name]
        if name
        else [f"{source.name[:190]} (copy)"]
        + [f"{source.name[:186]} (copy {n})" for n in range(2, 21)]
    )
    copy: Agent | None = None
    for candidate in candidates:
        try:
            async with session.begin_nested():
                copy = Agent(
                    org_id=ctx.org_id,
                    name=candidate,
                    description=source.description,
                    status=AgentStatus.DRAFT,
                    created_by_id=ctx.user.id,
                )
                session.add(copy)
                await session.flush()
            break
        except IntegrityError:
            copy = None
    if copy is None:
        raise _name_taken()

    new_version = await _insert_version(
        session, ctx, copy, config, approvals, f"Duplicated from {source.name}"
    )
    copy.current_version_id = new_version.id
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="agent.duplicated",
        resource_type="agent",
        resource_id=copy.id,
        details={"source_agent_id": str(source.id)},
    )
    await session.commit()
    return await agent_detail(session, ctx.org_id, copy)


async def delete_agent(session: AsyncSession, ctx: OrgContext, agent_id: uuid.UUID) -> None:
    """Soft delete: the agent leaves lists and cannot run; its runs and history are kept."""
    agent = await agent_repo.get(session, ctx.org_id, agent_id, lock=True)
    if agent is None:
        raise _not_found()
    agent.deleted_at = datetime.now(UTC)
    agent.status = AgentStatus.ARCHIVED
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="agent.deleted",
        resource_type="agent",
        resource_id=agent.id,
        details={"name": agent.name},
    )
    await session.commit()
