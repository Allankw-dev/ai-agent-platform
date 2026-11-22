import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from app.api.context import OrgContext
from app.api.deps import ResumeDispatcherDep, SessionDep, require
from app.core.permissions import Permission
from app.models.enums import ApprovalStatus
from app.schemas.approval import ApprovalDecision, ApprovalRead
from app.schemas.common import Page
from app.services import approvals as approval_service

router = APIRouter(prefix="/organizations/{org_id}/approvals", tags=["approvals"])

CanView = Annotated[OrgContext, Depends(require(Permission.APPROVALS_VIEW))]
CanDecide = Annotated[OrgContext, Depends(require(Permission.APPROVALS_DECIDE))]

LimitQuery = Annotated[int, Query(ge=1, le=100)]
OffsetQuery = Annotated[int, Query(ge=0)]
OptionalDecision = Annotated[ApprovalDecision | None, Body()]


@router.get("", response_model=Page[ApprovalRead])
async def list_approvals(
    ctx: CanView,
    session: SessionDep,
    status: ApprovalStatus | None = None,
    run_id: uuid.UUID | None = None,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> Page[ApprovalRead]:
    """The approvals inbox, newest first. Use `status=pending` for what is waiting."""
    items, total = await approval_service.list_approvals(
        session, ctx, status=status, run_id=run_id, limit=limit, offset=offset
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{approval_id}", response_model=ApprovalRead)
async def get_approval(approval_id: uuid.UUID, ctx: CanView, session: SessionDep) -> ApprovalRead:
    return await approval_service.get_approval(session, ctx, approval_id)


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
async def approve(
    approval_id: uuid.UUID,
    ctx: CanDecide,
    session: SessionDep,
    dispatch: ResumeDispatcherDep,
    body: OptionalDecision = None,
) -> ApprovalRead:
    """Let the action run exactly as shown. The run then continues."""
    note = body.note if body else None
    return await approval_service.decide(
        session, ctx, approval_id, ApprovalStatus.APPROVED, note, dispatch
    )


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
async def reject(
    approval_id: uuid.UUID,
    ctx: CanDecide,
    session: SessionDep,
    dispatch: ResumeDispatcherDep,
    body: OptionalDecision = None,
) -> ApprovalRead:
    """Do not run the action. The agent is told a person said no (with the note, if any)."""
    note = body.note if body else None
    return await approval_service.decide(
        session, ctx, approval_id, ApprovalStatus.REJECTED, note, dispatch
    )
