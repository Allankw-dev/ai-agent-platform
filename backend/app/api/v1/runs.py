import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response

from app.api.context import OrgContext
from app.api.deps import RunDispatcher, SessionDep, require
from app.core.permissions import Permission
from app.models.enums import RunStatus
from app.repositories import runs as run_repo
from app.schemas.common import Page
from app.schemas.run import RunCreate, RunDetail, RunRead
from app.services import runs as run_service

router = APIRouter(prefix="/organizations/{org_id}", tags=["runs"])

LimitQuery = Annotated[int, Query(ge=1, le=100)]
OffsetQuery = Annotated[int, Query(ge=0)]

CanView = Annotated[OrgContext, Depends(require(Permission.RUNS_VIEW))]
CanRun = Annotated[OrgContext, Depends(require(Permission.RUNS_CREATE))]


@router.post("/agents/{agent_id}/runs", response_model=RunRead, status_code=201)
async def create_run(
    agent_id: uuid.UUID,
    body: RunCreate,
    ctx: CanRun,
    session: SessionDep,
    dispatch: RunDispatcher,
    response: Response,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> RunRead:
    """Queue a run of the agent's current version.

    Send an `Idempotency-Key` header to make retries safe: the same key returns the original run
    (200) instead of starting another.
    """
    run, created = await run_service.create_run(
        session, ctx, agent_id, body, idempotency_key, dispatch
    )
    if not created:
        response.status_code = 200
    return run


@router.get("/runs", response_model=Page[RunRead])
async def list_runs(
    ctx: CanView,
    session: SessionDep,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
    agent_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
) -> Page[RunRead]:
    rows, total = await run_repo.list_for_org(
        session, ctx.org_id, limit, offset, agent_id=agent_id, status=status
    )
    items = [run_service.run_read(run, number) for run, number in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, ctx: CanView, session: SessionDep) -> RunDetail:
    return await run_service.get_run_detail(session, ctx, run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunRead)
async def cancel_run(run_id: uuid.UUID, ctx: CanRun, session: SessionDep) -> RunRead:
    return await run_service.cancel_run(session, ctx, run_id)
