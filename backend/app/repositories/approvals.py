import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent, AgentVersion, Tool
from app.models.enums import ApprovalStatus, RunStatus
from app.models.identity import User
from app.models.runs import AgentRun, Approval

TERMINAL_RUN_STATUSES = (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED)


@dataclass(frozen=True)
class ApprovalRow:
    """An approval with the labels people need to understand it."""

    approval: Approval
    agent_id: uuid.UUID
    agent_name: str
    agent_version: int
    tool_name: str | None
    decided_by_name: str | None


def _rows_query() -> Any:
    return (
        select(
            Approval,
            AgentRun.agent_id,
            Agent.name,
            AgentVersion.version,
            Tool.name,
            User.full_name,
            User.email,
        )
        .join(AgentRun, AgentRun.id == Approval.run_id)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
        .outerjoin(Tool, Tool.key == Approval.tool_key)
        .outerjoin(User, User.id == Approval.decided_by_id)
    )


def _row(values: Any) -> ApprovalRow:
    approval, agent_id, agent_name, version, tool_name, full_name, email = values
    return ApprovalRow(
        approval=approval,
        agent_id=agent_id,
        agent_name=str(agent_name),
        agent_version=int(version),
        tool_name=tool_name,
        decided_by_name=(full_name or email) if approval.decided_by_id else None,
    )


async def create(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    run_step_id: uuid.UUID,
    tool_key: str,
    proposed_input: dict[str, Any],
    reasoning_summary: str | None,
    expires_at: datetime,
) -> Approval:
    approval = Approval(
        org_id=org_id,
        run_id=run_id,
        run_step_id=run_step_id,
        tool_key=tool_key,
        proposed_input=proposed_input,
        reasoning_summary=reasoning_summary,
        status=ApprovalStatus.PENDING,
        expires_at=expires_at,
    )
    session.add(approval)
    await session.flush()
    return approval


async def get(session: AsyncSession, org_id: uuid.UUID, approval_id: uuid.UUID) -> Approval | None:
    return await session.scalar(
        select(Approval).where(Approval.org_id == org_id, Approval.id == approval_id)
    )


async def get_row(
    session: AsyncSession, org_id: uuid.UUID, approval_id: uuid.UUID
) -> ApprovalRow | None:
    result = await session.execute(
        _rows_query().where(Approval.org_id == org_id, Approval.id == approval_id)
    )
    values = result.first()
    return _row(values) if values else None


async def list_rows(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    status: ApprovalStatus | None,
    run_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[ApprovalRow], int]:
    count = select(func.count()).select_from(Approval).where(Approval.org_id == org_id)
    query = _rows_query().where(Approval.org_id == org_id)
    if status is not None:
        count = count.where(Approval.status == status)
        query = query.where(Approval.status == status)
    if run_id is not None:
        count = count.where(Approval.run_id == run_id)
        query = query.where(Approval.run_id == run_id)
    total = await session.scalar(count)
    result = await session.execute(
        query.order_by(Approval.requested_at.desc(), Approval.id).limit(limit).offset(offset)
    )
    return [_row(values) for values in result.all()], int(total or 0)


async def pending_for_run(session: AsyncSession, run_id: uuid.UUID) -> Approval | None:
    return await session.scalar(
        select(Approval).where(Approval.run_id == run_id, Approval.status == ApprovalStatus.PENDING)
    )


async def decide(
    session: AsyncSession,
    org_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    status: ApprovalStatus,
    user_id: uuid.UUID,
    note: str | None,
) -> bool:
    """Record a decision, atomically and only once.

    The single UPDATE succeeds only while the approval is still pending, has not expired, and its
    run is still waiting for it. A double click, two approvers at once, a late click after expiry
    or after the run was cancelled all find nothing to update and return False.
    """
    result = await session.execute(
        update(Approval)
        .where(
            Approval.org_id == org_id,
            Approval.id == approval_id,
            Approval.status == ApprovalStatus.PENDING,
            or_(Approval.expires_at.is_(None), Approval.expires_at > func.now()),
            exists().where(
                AgentRun.id == Approval.run_id, AgentRun.status == RunStatus.AWAITING_APPROVAL
            ),
        )
        .values(status=status, decided_by_id=user_id, decided_at=func.now(), decision_note=note)
        .returning(Approval.id)
    )
    return result.first() is not None


async def expire_due(session: AsyncSession, org_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Mark pending approvals past their expiry as expired. Returns (approval_id, run_id)."""
    result = await session.execute(
        update(Approval)
        .where(
            Approval.org_id == org_id,
            Approval.status == ApprovalStatus.PENDING,
            Approval.expires_at.is_not(None),
            Approval.expires_at <= func.now(),
        )
        .values(status=ApprovalStatus.EXPIRED, decided_at=func.now())
        .returning(Approval.id, Approval.run_id)
    )
    return [(row[0], row[1]) for row in result]


async def cancel_orphaned(
    session: AsyncSession, org_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Cancel pending approvals whose run has already ended (it was cancelled or failed).

    A run that is still running is left alone: it may be a moment away from pausing on one.
    """
    result = await session.execute(
        update(Approval)
        .where(
            Approval.org_id == org_id,
            Approval.status == ApprovalStatus.PENDING,
            exists().where(
                AgentRun.id == Approval.run_id, AgentRun.status.in_(TERMINAL_RUN_STATUSES)
            ),
        )
        .values(status=ApprovalStatus.CANCELLED, decided_at=func.now())
        .returning(Approval.id, Approval.run_id)
    )
    return [(row[0], row[1]) for row in result]


async def cancel_for_run(
    session: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID
) -> list[uuid.UUID]:
    result = await session.execute(
        update(Approval)
        .where(
            Approval.org_id == org_id,
            Approval.run_id == run_id,
            Approval.status == ApprovalStatus.PENDING,
        )
        .values(status=ApprovalStatus.CANCELLED, decided_at=func.now())
        .returning(Approval.id)
    )
    return [row[0] for row in result]
