"""The run event log (see docs/engine.md, "Run events and streaming").

`emit` is called from the same transaction that changes the run, so an event and the change it
describes commit together or not at all. A reader that sees the run in a final state is therefore
guaranteed to find the final event.
"""

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RunEventType
from app.models.runs import AgentRun, RunEvent


async def emit(
    session: AsyncSession,
    run_id: uuid.UUID,
    event_type: RunEventType,
    data: dict[str, Any] | None = None,
) -> int | None:
    """Append an event to a run and return its sequence number.

    The number comes from one atomic UPDATE on the run row (which locks it for the rest of the
    transaction), so two writers, say a worker finishing a step and a person cancelling, can never
    take the same number or leave a gap. Returns None when the run is not visible (it does not
    exist, or belongs to another organization): nothing is written then.

    `data` must hold ids, statuses and counts only. Never put tool arguments, tool output or
    message text in an event.
    """
    taken = (
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(event_seq=AgentRun.event_seq + 1)
            .returning(AgentRun.org_id, AgentRun.event_seq)
        )
    ).first()
    if taken is None:
        return None
    org_id, seq = taken
    session.add(RunEvent(org_id=org_id, run_id=run_id, seq=seq, type=event_type, data=data or {}))
    await session.flush()
    return int(seq)


async def list_after(
    session: AsyncSession, run_id: uuid.UUID, after: int, limit: int
) -> list[RunEvent]:
    """Events of a run with a sequence number greater than `after`, oldest first."""
    rows = await session.scalars(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.seq > after)
        .order_by(RunEvent.seq)
        .limit(limit)
    )
    return list(rows)
