"""Reading a run's event log: as a page of JSON, or as a live server-sent event stream.

The stream is built to survive reconnects: every frame carries its sequence number as the SSE
`id`, and a client that comes back passes the last one it saw (`after`, or the standard
`Last-Event-ID` header) and receives only what it missed.
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.context import OrgContext
from app.core.errors import ApiError
from app.db.tenancy import use_tenant
from app.models.enums import RunStatus
from app.models.runs import AgentRun
from app.repositories import run_events
from app.repositories import runs as run_repo
from app.schemas.run import RunEventRead

TERMINAL_STATUSES = (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED)
STREAM_BATCH = 100


async def require_run(session: AsyncSession, ctx: OrgContext, run_id: uuid.UUID) -> None:
    if await run_repo.get(session, ctx.org_id, run_id) is None:
        raise ApiError(404, "run_not_found", "Run not found.")


async def list_events(
    session: AsyncSession, ctx: OrgContext, run_id: uuid.UUID, after: int, limit: int
) -> list[RunEventRead]:
    await require_run(session, ctx, run_id)
    events = await run_events.list_after(session, run_id, after, limit)
    return [RunEventRead.model_validate(event) for event in events]


def parse_last_event_id(value: str | None) -> int:
    """The `Last-Event-ID` header as a sequence number; anything unusable counts as 0."""
    try:
        return max(int(value), 0) if value else 0
    except ValueError:
        return 0


def frame(event: RunEventRead) -> str:
    payload = event.model_dump(mode="json")
    return f"id: {event.seq}\nevent: {event.type.value}\ndata: {json.dumps(payload)}\n\n"


KEEP_ALIVE = ": keep-alive\n\n"


async def stream_events(
    maker: async_sessionmaker[AsyncSession],
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    after: int,
    poll_seconds: float,
    heartbeat_seconds: float,
    max_seconds: float,
) -> AsyncIterator[str]:
    """Yield SSE frames for a run until it ends, the connection reaches its time limit, or the
    client goes away.

    No database connection is held between polls: each poll is its own short transaction. The
    run's status is read *before* its events, in the same transaction. Events are written in the
    same transaction as the status change they describe, so seeing a final status guarantees the
    final event is already visible, and the stream can end without waiting for another poll.
    """
    cursor = after
    started = time.monotonic()
    last_sent = started
    while True:
        async with maker() as session:
            await use_tenant(session, org_id=org_id)
            status = await session.scalar(select(AgentRun.status).where(AgentRun.id == run_id))
            events = await run_events.list_after(session, run_id, cursor, STREAM_BATCH)
        if status is None:
            return
        for event in events:
            yield frame(RunEventRead.model_validate(event))
            cursor = event.seq
        now = time.monotonic()
        if events:
            last_sent = now
            if len(events) == STREAM_BATCH:
                continue  # more are waiting: read on without sleeping
        if status in TERMINAL_STATUSES:
            return
        if now - started >= max_seconds:
            return  # the client reconnects with the last sequence number it saw
        if now - last_sent >= heartbeat_seconds:
            yield KEEP_ALIVE
            last_sent = now
        await asyncio.sleep(poll_seconds)
