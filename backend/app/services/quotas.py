"""An organization's run limits: who may start a run right now, and what each run may use.

The check and the reservation happen in one transaction under an advisory lock (see
repositories/quotas.lock_org_runs), so simultaneous requests cannot slip past a limit together.
Nothing here keeps counters in memory: every worker and API process reads the same database rows.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.model_price import ModelPrice
from app.engine.limits import EffectiveLimits
from app.repositories import quotas as quota_repo
from app.schemas.quota import (
    AgentUsage,
    OrgLimitsRead,
    OrgLimitsUpdate,
    UsageDay,
    UsageRead,
    UsageToday,
)
from app.services import audit

USAGE_AGENT_ROWS = 10
MICRO = Decimal(1_000_000)
USD = Decimal("0.000001")


@dataclass(frozen=True)
class EffectiveOrgLimits:
    max_concurrent_runs: int
    daily_token_quota: int
    daily_cost_quota_usd: Decimal | None
    customized: bool
    updated_at: datetime | None


@dataclass(frozen=True)
class Reservation:
    tokens: int
    cost_usd: Decimal | None


async def effective_org_limits(
    session: AsyncSession, org_id: uuid.UUID, settings: Settings | None = None
) -> EffectiveOrgLimits:
    settings = settings or get_settings()
    row = await quota_repo.get_limits(session, org_id)
    if row is None:
        return EffectiveOrgLimits(
            max_concurrent_runs=settings.org_default_max_concurrent_runs,
            daily_token_quota=settings.org_default_daily_token_quota,
            daily_cost_quota_usd=settings.org_default_daily_cost_quota_usd,
            customized=False,
            updated_at=None,
        )
    return EffectiveOrgLimits(
        max_concurrent_runs=row.max_concurrent_runs,
        daily_token_quota=row.daily_token_quota,
        daily_cost_quota_usd=row.daily_cost_quota_usd,
        customized=True,
        updated_at=row.updated_at,
    )


def limits_read(limits: EffectiveOrgLimits) -> OrgLimitsRead:
    return OrgLimitsRead(
        max_concurrent_runs=limits.max_concurrent_runs,
        daily_token_quota=limits.daily_token_quota,
        daily_cost_quota_usd=(
            None if limits.daily_cost_quota_usd is None else float(limits.daily_cost_quota_usd)
        ),
        customized=limits.customized,
        updated_at=limits.updated_at,
    )


def worst_case_cost_usd(prices: dict[str, ModelPrice], model: str, tokens: int) -> Decimal | None:
    """The most `tokens` tokens could cost on `model`, or None if it has no configured price."""
    price = prices.get(model)
    if price is None:
        return None
    rate = max(
        price.input_per_mtok,
        price.output_per_mtok,
        price.long_input_per_mtok or Decimal(0),
        price.long_output_per_mtok or Decimal(0),
    )
    return (rate * tokens / MICRO).quantize(USD)


def seconds_until_reset(now: datetime | None = None) -> int:
    moment = now or datetime.now(UTC)
    return max(1, int((quota_repo.day_start(moment) + timedelta(days=1) - moment).total_seconds()))


def _quota_message(limits: EffectiveOrgLimits, what: str) -> str:
    return (
        f"This organization has used its daily {what} quota. It resets at midnight UTC. "
        "An owner or admin can raise the quota under Usage."
    )


async def reserve_for_run(
    session: AsyncSession, org_id: uuid.UUID, run_limits: EffectiveLimits, model: str
) -> Reservation:
    """Check the organization's limits for one more run and work out what it reserves.

    Raises a 429 (concurrency or daily quota reached) or a 409 (the run could never fit, or its
    cost cannot be limited) without creating anything. Must run in the same transaction that
    inserts the run, so that the lock covers both.
    """
    settings = get_settings()
    await quota_repo.lock_org_runs(session, org_id)
    limits = await effective_org_limits(session, org_id, settings)

    busy = await quota_repo.busy_runs(session, org_id)
    if busy >= limits.max_concurrent_runs:
        raise ApiError(
            429,
            "concurrency_limit_reached",
            f"This organization already has {busy} runs queued or running "
            f"(the limit is {limits.max_concurrent_runs}). Wait for one to finish, or ask an "
            "owner or admin to raise the limit under Usage.",
        )

    need_tokens = run_limits.max_total_tokens
    if need_tokens > limits.daily_token_quota:
        raise ApiError(
            409,
            "run_exceeds_daily_quota",
            f"This agent may use up to {need_tokens:,} tokens in one run, more than the "
            f"organization's whole daily quota of {limits.daily_token_quota:,}. Lower the agent's "
            "token limit, or ask an owner or admin to raise the quota under Usage.",
        )

    need_cost: Decimal | None = (
        None if run_limits.cost_budget_usd is None else Decimal(str(run_limits.cost_budget_usd))
    )
    if limits.daily_cost_quota_usd is not None and need_cost is None:
        need_cost = worst_case_cost_usd(settings.model_prices, model, need_tokens)
        if need_cost is None:
            raise ApiError(
                409,
                "cost_quota_needs_price",
                f"The organization has a daily cost quota, but the model {model!r} has no price "
                "configured on this platform (MODEL_PRICES), so this agent's cost cannot be "
                "limited. Give the agent a cost budget, or ask the platform admin to add a price.",
            )
    if (
        limits.daily_cost_quota_usd is not None
        and need_cost is not None
        and need_cost > limits.daily_cost_quota_usd
    ):
        raise ApiError(
            409,
            "run_exceeds_daily_quota",
            f"This agent may spend up to ${need_cost} in one run, more than the organization's "
            f"whole daily cost quota of ${limits.daily_cost_quota_usd}.",
        )

    input_tokens, output_tokens, spent_usd = await quota_repo.used_since(
        session, org_id, quota_repo.day_start()
    )
    held_tokens, held_usd = await quota_repo.open_reservations(session, org_id)
    retry = {"Retry-After": str(seconds_until_reset())}
    if input_tokens + output_tokens + held_tokens + need_tokens > limits.daily_token_quota:
        raise ApiError(429, "daily_quota_reached", _quota_message(limits, "token"), headers=retry)
    if (
        limits.daily_cost_quota_usd is not None
        and need_cost is not None
        and spent_usd + held_usd + need_cost > limits.daily_cost_quota_usd
    ):
        raise ApiError(429, "daily_quota_reached", _quota_message(limits, "cost"), headers=retry)
    return Reservation(tokens=need_tokens, cost_usd=need_cost)


async def get_org_limits(session: AsyncSession, ctx: OrgContext) -> OrgLimitsRead:
    return limits_read(await effective_org_limits(session, ctx.org_id))


async def set_org_limits(
    session: AsyncSession, ctx: OrgContext, body: OrgLimitsUpdate
) -> OrgLimitsRead:
    before = await effective_org_limits(session, ctx.org_id)
    await quota_repo.save_limits(
        session,
        ctx.org_id,
        ctx.user.id,
        max_concurrent_runs=body.max_concurrent_runs,
        daily_token_quota=body.daily_token_quota,
        daily_cost_quota_usd=body.daily_cost_quota_usd,
    )
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="org.limits_updated",
        resource_type="organization",
        resource_id=ctx.org_id,
        details={
            "from": _audit_view(before),
            "to": {
                "max_concurrent_runs": body.max_concurrent_runs,
                "daily_token_quota": body.daily_token_quota,
                "daily_cost_quota_usd": (
                    None if body.daily_cost_quota_usd is None else str(body.daily_cost_quota_usd)
                ),
            },
        },
    )
    await session.commit()
    return await get_org_limits(session, ctx)


async def reset_org_limits(session: AsyncSession, ctx: OrgContext) -> None:
    before = await effective_org_limits(session, ctx.org_id)
    if await quota_repo.delete_limits(session, ctx.org_id):
        await audit.record(
            session,
            org_id=ctx.org_id,
            actor_id=ctx.user.id,
            action="org.limits_reset",
            resource_type="organization",
            resource_id=ctx.org_id,
            details={"from": _audit_view(before)},
        )
    await session.commit()


def _audit_view(limits: EffectiveOrgLimits) -> dict[str, object]:
    return {
        "max_concurrent_runs": limits.max_concurrent_runs,
        "daily_token_quota": limits.daily_token_quota,
        "daily_cost_quota_usd": (
            None if limits.daily_cost_quota_usd is None else str(limits.daily_cost_quota_usd)
        ),
        "customized": limits.customized,
    }


async def usage(session: AsyncSession, ctx: OrgContext, days: int) -> UsageRead:
    limits = await effective_org_limits(session, ctx.org_id)
    today_start = quota_repo.day_start()
    since = today_start - timedelta(days=days - 1)

    input_tokens, output_tokens, cost = await quota_repo.used_since(
        session, ctx.org_id, today_start
    )
    held_tokens, _held_usd = await quota_repo.open_reservations(session, ctx.org_id)
    busy = await quota_repo.busy_runs(session, ctx.org_id)
    per_day = await quota_repo.usage_by_day(session, ctx.org_id, since)
    runs = await quota_repo.runs_by_day(session, ctx.org_id, since)
    agents = await quota_repo.usage_by_agent(session, ctx.org_id, since, USAGE_AGENT_ROWS)

    series: list[UsageDay] = []
    for offset in range(days):
        day = (since + timedelta(days=offset)).date()
        used_in, used_out, used_cost = per_day.get(day, (0, 0, Decimal(0)))
        series.append(
            UsageDay(
                day=day,
                runs=runs.get(day, 0),
                input_tokens=used_in,
                output_tokens=used_out,
                cost_usd=float(used_cost),
            )
        )
    return UsageRead(
        limits=limits_read(limits),
        today=UsageToday(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=float(cost),
            reserved_tokens=held_tokens,
            busy_runs=busy,
            resets_at=today_start + timedelta(days=1),
        ),
        days=series,
        by_agent=[
            AgentUsage(
                agent_id=agent_id,
                agent_name=name,
                input_tokens=used_in,
                output_tokens=used_out,
                cost_usd=float(used_cost),
            )
            for agent_id, name, used_in, used_out, used_cost in agents
        ],
    )
