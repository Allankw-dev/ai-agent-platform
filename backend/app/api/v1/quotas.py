from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.context import OrgContext
from app.api.deps import SessionDep, require
from app.core.permissions import Permission
from app.schemas.quota import OrgLimitsRead, OrgLimitsUpdate, UsageRead
from app.services import quotas as quota_service

router = APIRouter(prefix="/organizations/{org_id}", tags=["usage"])

CanViewUsage = Annotated[OrgContext, Depends(require(Permission.USAGE_VIEW))]
CanViewLimits = Annotated[OrgContext, Depends(require(Permission.LIMITS_VIEW))]
CanManageLimits = Annotated[OrgContext, Depends(require(Permission.LIMITS_MANAGE))]


@router.get("/limits", response_model=OrgLimitsRead)
async def get_limits(ctx: CanViewLimits, session: SessionDep) -> OrgLimitsRead:
    """The organization's run limits (the platform defaults until an admin sets their own)."""
    return await quota_service.get_org_limits(session, ctx)


@router.put("/limits", response_model=OrgLimitsRead)
async def set_limits(
    body: OrgLimitsUpdate, ctx: CanManageLimits, session: SessionDep
) -> OrgLimitsRead:
    return await quota_service.set_org_limits(session, ctx, body)


@router.delete("/limits", status_code=204)
async def reset_limits(ctx: CanManageLimits, session: SessionDep) -> Response:
    """Go back to the platform defaults."""
    await quota_service.reset_org_limits(session, ctx)
    return Response(status_code=204)


@router.get("/usage", response_model=UsageRead)
async def get_usage(
    ctx: CanViewUsage,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> UsageRead:
    """Today against the daily quota, the last `days` days, and the heaviest agents."""
    return await quota_service.usage(session, ctx, days)
