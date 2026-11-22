"""Approvals: a person deciding whether an agent's action may run.

The engine records an approval and pauses the run (see `app/engine/graph.py`). This module is the
people side: list and read approvals, decide them, and keep the clock honest.

Deciding is one atomic database update that succeeds only while the approval is pending, has not
expired, and its run is still waiting, so a double click, two approvers at once, or a late click
after expiry or cancellation cannot decide twice. A decision then hands the run back to a worker
(`agents.resume_run`).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.context import OrgContext
from app.core.errors import ApiError
from app.db.tenancy import use_tenant
from app.models.enums import ApprovalStatus, RunStatus
from app.repositories import approvals as approval_repo
from app.repositories import runs as run_repo
from app.repositories.approvals import ApprovalRow
from app.schemas.approval import ApprovalRead, ApprovalSummary
from app.services import audit

log = structlog.get_logger()

# Hands a decided run back to a worker: (run_id, org_id). Replaceable in tests.
ResumeDispatcher = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]

EXPIRED_RUN = (
    "An approval request expired before anyone decided, so the action was not run and the run "
    "was stopped."
)
EXPIRED_STEP = "Nobody decided in time, so this action was not run."
ENDED_STEP = "The run ended before anyone decided, so this action was not run."


async def celery_resume_dispatcher(run_id: uuid.UUID, org_id: uuid.UUID) -> None:
    from app.workers.tasks import resume_run_task

    # `.delay` talks to the broker synchronously, so keep it off the event loop.
    await asyncio.to_thread(resume_run_task.delay, str(run_id), str(org_id))


def seconds_left(row: ApprovalRow, now: datetime | None = None) -> int | None:
    approval = row.approval
    if approval.status is not ApprovalStatus.PENDING or approval.expires_at is None:
        return None
    return max(0, int((approval.expires_at - (now or datetime.now(UTC))).total_seconds()))


def read(row: ApprovalRow) -> ApprovalRead:
    approval = row.approval
    return ApprovalRead(
        id=approval.id,
        run_id=approval.run_id,
        run_step_id=approval.run_step_id,
        agent_id=row.agent_id,
        agent_name=row.agent_name,
        agent_version=row.agent_version,
        tool_key=approval.tool_key,
        tool_name=row.tool_name,
        proposed_input=approval.proposed_input,
        reasoning_summary=approval.reasoning_summary,
        status=approval.status,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        seconds_left=seconds_left(row),
        decided_by_id=approval.decided_by_id,
        decided_by_name=row.decided_by_name,
        decided_at=approval.decided_at,
        decision_note=approval.decision_note,
    )


def summary_of(approval_row: ApprovalRow) -> ApprovalSummary:
    approval = approval_row.approval
    return ApprovalSummary(
        id=approval.id,
        tool_key=approval.tool_key,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        seconds_left=seconds_left(approval_row),
    )


async def sweep(session: AsyncSession, ctx: OrgContext) -> None:
    """Expire approvals past their time and cancel ones whose run already ended.

    Runs on reads and before a decision, in its own short transaction, so a plain GET never leaves
    an expired approval looking open and the request's own transaction is left alone.
    """
    maintenance_sessions = async_sessionmaker(bind=session.bind, expire_on_commit=False)
    async with maintenance_sessions() as work:
        await use_tenant(work, user_id=ctx.user.id, org_id=ctx.org_id)
        changed = False
        for approval_id, run_id in await approval_repo.expire_due(work, ctx.org_id):
            changed = True
            await run_repo.fail_awaiting(work, run_id, EXPIRED_RUN)
            await run_repo.end_awaiting_steps(work, [run_id], EXPIRED_STEP)
            await audit.record(
                work,
                org_id=ctx.org_id,
                actor_id=None,
                action="approval.expired",
                resource_type="approval",
                resource_id=approval_id,
                details={"run_id": str(run_id)},
            )
        for approval_id, run_id in await approval_repo.cancel_orphaned(work, ctx.org_id):
            changed = True
            await run_repo.end_awaiting_steps(work, [run_id], ENDED_STEP)
            await audit.record(
                work,
                org_id=ctx.org_id,
                actor_id=None,
                action="approval.cancelled",
                resource_type="approval",
                resource_id=approval_id,
                details={"run_id": str(run_id)},
            )
        if changed:
            await work.commit()


async def list_approvals(
    session: AsyncSession,
    ctx: OrgContext,
    *,
    status: ApprovalStatus | None,
    run_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[ApprovalRead], int]:
    await sweep(session, ctx)
    rows, total = await approval_repo.list_rows(
        session, ctx.org_id, status=status, run_id=run_id, limit=limit, offset=offset
    )
    return [read(row) for row in rows], total


async def get_approval(
    session: AsyncSession, ctx: OrgContext, approval_id: uuid.UUID
) -> ApprovalRead:
    await sweep(session, ctx)
    row = await approval_repo.get_row(session, ctx.org_id, approval_id)
    if row is None:
        raise ApiError(404, "approval_not_found", "Approval not found.")
    return read(row)


def _conflict(row: ApprovalRow, run_status: RunStatus | None) -> ApiError:
    """Why a decision could not be recorded, in plain words."""
    status = row.approval.status
    if status is ApprovalStatus.EXPIRED:
        return ApiError(
            409,
            "approval_expired",
            "This approval expired before anyone decided, so it can no longer be decided.",
        )
    if status is ApprovalStatus.CANCELLED:
        return ApiError(
            409,
            "approval_cancelled",
            "The run ended before anyone decided, so there is nothing to approve.",
        )
    if status is ApprovalStatus.PENDING:
        if run_status is RunStatus.RUNNING:
            return ApiError(
                409,
                "approval_not_ready",
                "The run is still getting ready for this decision. Try again in a moment.",
            )
        return ApiError(
            409, "approval_not_actionable", "The run is no longer waiting for this approval."
        )
    who = f" by {row.decided_by_name}" if row.decided_by_name else ""
    return ApiError(
        409, "approval_already_decided", f"This approval was already {status.value}{who}."
    )


async def decide(
    session: AsyncSession,
    ctx: OrgContext,
    approval_id: uuid.UUID,
    decision: ApprovalStatus,
    note: str | None,
    dispatch: ResumeDispatcher,
) -> ApprovalRead:
    """Approve or reject. Returns the updated approval, or raises 404 or 409 with the reason."""
    if decision not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
        raise ValueError("decision must be approved or rejected")
    await sweep(session, ctx)
    before = await approval_repo.get_row(session, ctx.org_id, approval_id)
    if before is None:
        raise ApiError(404, "approval_not_found", "Approval not found.")

    decided = await approval_repo.decide(
        session, ctx.org_id, approval_id, status=decision, user_id=ctx.user.id, note=note
    )
    if decided:
        await audit.record(
            session,
            org_id=ctx.org_id,
            actor_id=ctx.user.id,
            action=f"approval.{decision.value}",
            resource_type="approval",
            resource_id=approval_id,
            details={
                "run_id": str(before.approval.run_id),
                "tool_key": before.approval.tool_key,
                "has_note": note is not None,
            },
        )
        await session.commit()
        await _resume(dispatch, before.approval.run_id, ctx.org_id)
    else:
        # Nothing was changed (the update matched no row), so there is nothing to roll back.
        # Find out why, after letting the clock catch up.
        await sweep(session, ctx)
        current = await approval_repo.get_row(session, ctx.org_id, approval_id)
        if current is None:  # pragma: no cover - rows are never deleted
            raise ApiError(404, "approval_not_found", "Approval not found.")
        run = await run_repo.get(session, ctx.org_id, current.approval.run_id)
        run_status = run.status if run else None
        if current.approval.status is decision and run_status is RunStatus.AWAITING_APPROVAL:
            # The same decision again while the run still waits: the first attempt may have been
            # saved but never handed to a worker, so hand it over again. Harmless if it was.
            await _resume(dispatch, current.approval.run_id, ctx.org_id)
        else:
            raise _conflict(current, run_status)

    row = await approval_repo.get_row(session, ctx.org_id, approval_id)
    if row is None:  # pragma: no cover - rows are never deleted
        raise ApiError(404, "approval_not_found", "Approval not found.")
    return read(row)


async def _resume(dispatch: ResumeDispatcher, run_id: uuid.UUID, org_id: uuid.UUID) -> None:
    try:
        await dispatch(run_id, org_id)
    except Exception as exc:
        log.exception("approvals.resume_dispatch_failed", run_id=str(run_id))
        raise ApiError(
            503,
            "queue_unavailable",
            "The decision was saved, but the run could not be continued right now. "
            "Press the button again to retry.",
        ) from exc
