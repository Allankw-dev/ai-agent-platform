import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.context import OrgContext
from app.api.deps import RunDispatcher, SessionDep, require
from app.core.config import get_settings
from app.core.permissions import Permission
from app.models.enums import RunStatus
from app.repositories import runs as run_repo
from app.schemas.common import Page
from app.schemas.run import RunCreate, RunDetail, RunEventList, RunRead
from app.services import run_events as event_service
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
    await run_service.reap_orphaned_runs(session, ctx)
    rows, total = await run_repo.list_for_org(
        session, ctx.org_id, limit, offset, agent_id=agent_id, status=status
    )
    items = [run_service.run_read(run, number, name) for run, number, name in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, ctx: CanView, session: SessionDep) -> RunDetail:
    return await run_service.get_run_detail(session, ctx, run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunRead)
async def cancel_run(run_id: uuid.UUID, ctx: CanRun, session: SessionDep) -> RunRead:
    return await run_service.cancel_run(session, ctx, run_id)


@router.get("/runs/{run_id}/events", response_model=RunEventList)
async def list_run_events(
    run_id: uuid.UUID,
    ctx: CanView,
    session: SessionDep,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> RunEventList:
    """What happened to a run, oldest first. Pass the last `seq` you saw as `after` to page on."""
    return RunEventList(items=await event_service.list_events(session, ctx, run_id, after, limit))


@router.get("/runs/{run_id}/events/stream")
async def stream_run_events(
    run_id: uuid.UUID,
    ctx: CanView,
    session: SessionDep,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Live events of a run as server-sent events (`text/event-stream`).

    Each frame's `id` is its sequence number. After a dropped connection, reconnect with
    `after=<last seq seen>` (or the standard `Last-Event-ID` header) to receive only what was
    missed. The stream ends when the run finishes, and after a few minutes at most so that
    clients reconnect; keep-alive comments are sent while nothing happens. Send the same
    `Authorization` header as for any other call (use `fetch`, not `EventSource`).
    """
    await event_service.require_run(session, ctx, run_id)
    settings = get_settings()
    maker = async_sessionmaker(bind=session.bind, expire_on_commit=False)
    # Give the connection back now: the stream polls with short transactions of its own and must
    # not hold one from the request's session for as long as it stays open.
    await session.rollback()
    frames = event_service.stream_events(
        maker,
        org_id=ctx.org_id,
        run_id=run_id,
        after=max(after, event_service.parse_last_event_id(last_event_id)),
        poll_seconds=settings.run_stream_poll_seconds,
        heartbeat_seconds=settings.run_stream_heartbeat_seconds,
        max_seconds=settings.run_stream_max_seconds,
    )
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
