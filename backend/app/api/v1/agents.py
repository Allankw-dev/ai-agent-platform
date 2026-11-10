import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.context import OrgContext
from app.api.deps import SessionDep, require
from app.core.permissions import Permission
from app.models.enums import AgentStatus
from app.schemas.agent import (
    AgentCreate,
    AgentListItem,
    AgentRead,
    AgentUpdate,
    DuplicateRequest,
    RollbackRequest,
    VersionCreate,
    VersionRead,
    VersionSummary,
)
from app.schemas.common import Page
from app.services import agents as agent_service

router = APIRouter(prefix="/organizations/{org_id}/agents", tags=["agents"])

CanViewAgents = Annotated[OrgContext, Depends(require(Permission.AGENTS_VIEW))]
CanManageAgents = Annotated[OrgContext, Depends(require(Permission.AGENTS_MANAGE))]

LimitQuery = Annotated[int, Query(ge=1, le=100)]
OffsetQuery = Annotated[int, Query(ge=0)]


@router.post("", response_model=AgentRead, status_code=201)
async def create_agent(body: AgentCreate, ctx: CanManageAgents, session: SessionDep) -> AgentRead:
    return await agent_service.create_agent(session, ctx, body)


@router.get("", response_model=Page[AgentListItem])
async def list_agents(
    ctx: CanViewAgents,
    session: SessionDep,
    status: AgentStatus | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> Page[AgentListItem]:
    items, total = await agent_service.list_agents(
        session, ctx, status=status, query=q, limit=limit, offset=offset
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: uuid.UUID, ctx: CanViewAgents, session: SessionDep) -> AgentRead:
    return await agent_service.get_agent(session, ctx, agent_id)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: uuid.UUID, body: AgentUpdate, ctx: CanManageAgents, session: SessionDep
) -> AgentRead:
    return await agent_service.update_agent(session, ctx, agent_id, body)


@router.delete("/{agent_id}", status_code=204, response_class=Response)
async def delete_agent(agent_id: uuid.UUID, ctx: CanManageAgents, session: SessionDep) -> Response:
    await agent_service.delete_agent(session, ctx, agent_id)
    return Response(status_code=204)


@router.post("/{agent_id}/duplicate", response_model=AgentRead, status_code=201)
async def duplicate_agent(
    agent_id: uuid.UUID, body: DuplicateRequest, ctx: CanManageAgents, session: SessionDep
) -> AgentRead:
    return await agent_service.duplicate(session, ctx, agent_id, body.name)


@router.get("/{agent_id}/versions", response_model=Page[VersionSummary])
async def list_versions(
    agent_id: uuid.UUID,
    ctx: CanViewAgents,
    session: SessionDep,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> Page[VersionSummary]:
    items, total = await agent_service.list_versions(session, ctx, agent_id, limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/{agent_id}/versions", response_model=VersionRead, status_code=201)
async def create_version(
    agent_id: uuid.UUID, body: VersionCreate, ctx: CanManageAgents, session: SessionDep
) -> VersionRead:
    return await agent_service.create_version(session, ctx, agent_id, body.config, body.change_note)


@router.get("/{agent_id}/versions/{number}", response_model=VersionRead)
async def get_version(
    agent_id: uuid.UUID, number: int, ctx: CanViewAgents, session: SessionDep
) -> VersionRead:
    return await agent_service.get_version(session, ctx, agent_id, number)


@router.post("/{agent_id}/rollback", response_model=AgentRead)
async def rollback_agent(
    agent_id: uuid.UUID, body: RollbackRequest, ctx: CanManageAgents, session: SessionDep
) -> AgentRead:
    return await agent_service.rollback(session, ctx, agent_id, body.version)
