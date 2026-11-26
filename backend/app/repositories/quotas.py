"""Queries behind the organization's run limits, daily quotas and usage totals.

Reservations live on `agent_runs` (reserved_tokens, reserved_cost_usd) and count only while a run
is open. There is deliberately no separate "settle" step: a run that succeeds, fails, is cancelled,
expires or is cleaned up as an orphan stops being open, and its reservation stops counting with it.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent
from app.models.enums import RunStatus
from app.models.runs import AgentRun
from app.models.usage import OrgLimits, UsageRecord

OPEN_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL)
# Runs that occupy a worker slot. A run waiting for a person holds none.
BUSY_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)


def day_start(now: datetime | None = None) -> datetime:
    """Midnight UTC of the current day: when the daily quota last reset."""
    moment = now or datetime.now(UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


async def lock_org_runs(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Serialize run creation within one organization until the transaction ends.

    Without it two requests could both see room for one more run and both take it. The lock is
    held for the few milliseconds between counting and inserting, never across a model call.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"org-runs:{org_id}"},
    )


async def get_limits(session: AsyncSession, org_id: uuid.UUID) -> OrgLimits | None:
    return await session.scalar(select(OrgLimits).where(OrgLimits.org_id == org_id))


async def save_limits(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    max_concurrent_runs: int,
    daily_token_quota: int,
    daily_cost_quota_usd: Decimal | None,
) -> OrgLimits:
    values: dict[str, Any] = {
        "org_id": org_id,
        "max_concurrent_runs": max_concurrent_runs,
        "daily_token_quota": daily_token_quota,
        "daily_cost_quota_usd": daily_cost_quota_usd,
        "updated_by_id": user_id,
        "updated_at": func.now(),
    }
    statement = (
        insert(OrgLimits)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_org_limits_org_id",
            set_={key: value for key, value in values.items() if key != "org_id"},
        )
        .returning(OrgLimits)
    )
    saved: OrgLimits = (
        await session.scalars(statement, execution_options={"populate_existing": True})
    ).one()
    return saved


async def delete_limits(session: AsyncSession, org_id: uuid.UUID) -> bool:
    deleted = await session.execute(
        text("DELETE FROM org_limits WHERE org_id = :org RETURNING id"), {"org": org_id}
    )
    return deleted.first() is not None


async def busy_runs(session: AsyncSession, org_id: uuid.UUID) -> int:
    """Runs queued or running: the ones that need a worker."""
    count = await session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.org_id == org_id, AgentRun.status.in_(BUSY_STATUSES))
    )
    return int(count or 0)


async def open_reservations(session: AsyncSession, org_id: uuid.UUID) -> tuple[int, Decimal]:
    """What open runs may still use: each run's reservation minus what it has already spent.

    Spending is subtracted because it is already counted in today's usage; counting it in both
    places would make every long-lived run look twice as expensive.
    """
    spent_tokens = AgentRun.input_tokens + AgentRun.output_tokens
    row = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(func.greatest(AgentRun.reserved_tokens - spent_tokens, 0)), 0
                ),
                func.coalesce(
                    func.sum(
                        func.greatest(
                            func.coalesce(AgentRun.reserved_cost_usd, 0) - AgentRun.cost_usd, 0
                        )
                    ),
                    0,
                ),
            ).where(AgentRun.org_id == org_id, AgentRun.status.in_(OPEN_STATUSES))
        )
    ).one()
    return int(row[0]), Decimal(row[1])


async def used_since(
    session: AsyncSession, org_id: uuid.UUID, since: datetime
) -> tuple[int, int, Decimal]:
    """(input tokens, output tokens, cost in USD) recorded since `since`."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_usd), 0),
            ).where(UsageRecord.org_id == org_id, UsageRecord.occurred_at >= since)
        )
    ).one()
    return int(row[0]), int(row[1]), Decimal(row[2])


async def usage_by_day(
    session: AsyncSession, org_id: uuid.UUID, since: datetime
) -> dict[Any, tuple[int, int, Decimal]]:
    day = cast(func.timezone("UTC", UsageRecord.occurred_at), Date)
    rows = await session.execute(
        select(
            day,
            func.sum(UsageRecord.input_tokens),
            func.sum(UsageRecord.output_tokens),
            func.sum(UsageRecord.cost_usd),
        )
        .where(UsageRecord.org_id == org_id, UsageRecord.occurred_at >= since)
        .group_by(day)
    )
    return {r[0]: (int(r[1]), int(r[2]), Decimal(r[3])) for r in rows}


async def runs_by_day(session: AsyncSession, org_id: uuid.UUID, since: datetime) -> dict[Any, int]:
    day = cast(func.timezone("UTC", AgentRun.created_at), Date)
    rows = await session.execute(
        select(day, func.count())
        .where(AgentRun.org_id == org_id, AgentRun.created_at >= since)
        .group_by(day)
    )
    return {r[0]: int(r[1]) for r in rows}


async def usage_by_agent(
    session: AsyncSession, org_id: uuid.UUID, since: datetime, limit: int
) -> list[tuple[uuid.UUID, str, int, int, Decimal]]:
    """Heaviest agents first. Agents deleted since then still show, under their own name."""
    total = func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens)
    rows = await session.execute(
        select(
            Agent.id,
            Agent.name,
            func.sum(UsageRecord.input_tokens),
            func.sum(UsageRecord.output_tokens),
            func.sum(UsageRecord.cost_usd),
        )
        .join(Agent, (Agent.id == UsageRecord.agent_id) & (Agent.org_id == UsageRecord.org_id))
        .where(UsageRecord.org_id == org_id, UsageRecord.occurred_at >= since)
        .group_by(Agent.id, Agent.name)
        .order_by(total.desc())
        .limit(limit)
    )
    return [(r[0], r[1], int(r[2]), int(r[3]), Decimal(r[4])) for r in rows]
