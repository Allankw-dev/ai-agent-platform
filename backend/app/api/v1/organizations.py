import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.context import OrgContext
from app.api.deps import CurrentUser, OrgCtx, SessionDep, require
from app.core.errors import ApiError
from app.core.permissions import Permission
from app.models.enums import OrgRole
from app.repositories import invitations as invitation_repo
from app.repositories import members as member_repo
from app.repositories import organizations as org_repo
from app.schemas.common import Page
from app.schemas.organization import (
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    MemberRead,
    MemberRoleUpdate,
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationWithRole,
)
from app.services import invitations as invitation_service
from app.services import members as member_service
from app.services import organizations as org_service

router = APIRouter(prefix="/organizations", tags=["organizations"])

LimitQuery = Annotated[int, Query(ge=1, le=100)]
OffsetQuery = Annotated[int, Query(ge=0)]

CanUpdateOrg = Annotated[OrgContext, Depends(require(Permission.ORG_UPDATE))]
CanDeleteOrg = Annotated[OrgContext, Depends(require(Permission.ORG_DELETE))]
CanViewMembers = Annotated[OrgContext, Depends(require(Permission.MEMBERS_VIEW))]
CanManageMembers = Annotated[OrgContext, Depends(require(Permission.MEMBERS_MANAGE))]


# ---------- organizations ----------


@router.post("", response_model=OrganizationWithRole, status_code=201)
async def create_organization(
    body: OrganizationCreate, user: CurrentUser, session: SessionDep
) -> OrganizationWithRole:
    organization = await org_service.create_organization(session, user, body.name, body.slug)
    return OrganizationWithRole(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        created_at=organization.created_at,
        role=OrgRole.OWNER,
    )


@router.get("", response_model=Page[OrganizationWithRole])
async def list_my_organizations(
    user: CurrentUser,
    session: SessionDep,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> Page[OrganizationWithRole]:
    rows, total = await org_repo.list_for_user(session, user.id, limit, offset)
    items = [
        OrganizationWithRole(
            id=org.id, name=org.name, slug=org.slug, created_at=org.created_at, role=role
        )
        for org, role in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{org_id}", response_model=OrganizationWithRole)
async def get_organization(ctx: OrgCtx, session: SessionDep) -> OrganizationWithRole:
    organization = await org_repo.get(session, ctx.org_id)
    if organization is None:  # pragma: no cover - membership was just verified
        raise ApiError(404, "organization_not_found", "Organization not found.")
    return OrganizationWithRole(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        created_at=organization.created_at,
        role=ctx.role,
    )


@router.patch("/{org_id}", response_model=OrganizationWithRole)
async def update_organization(
    body: OrganizationUpdate, ctx: CanUpdateOrg, session: SessionDep
) -> OrganizationWithRole:
    organization = await org_service.rename_organization(session, ctx, body.name)
    return OrganizationWithRole(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        created_at=organization.created_at,
        role=ctx.role,
    )


@router.delete("/{org_id}", status_code=204, response_class=Response)
async def delete_organization(ctx: CanDeleteOrg, session: SessionDep) -> Response:
    await org_service.delete_organization(session, ctx)
    return Response(status_code=204)


# ---------- members ----------


@router.get("/{org_id}/members", response_model=Page[MemberRead])
async def list_members(
    ctx: CanViewMembers,
    session: SessionDep,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> Page[MemberRead]:
    rows, total = await member_repo.list_with_users(session, ctx.org_id, limit, offset)
    items = [
        MemberRead(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=member.role,
            joined_at=member.created_at,
        )
        for member, user in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.patch("/{org_id}/members/{user_id}", response_model=MemberRoleUpdate)
async def change_member_role(
    user_id: uuid.UUID, body: MemberRoleUpdate, ctx: CanManageMembers, session: SessionDep
) -> MemberRoleUpdate:
    role = await member_service.change_role(session, ctx, user_id, body.role)
    return MemberRoleUpdate(role=role)


@router.delete("/{org_id}/members/{user_id}", status_code=204, response_class=Response)
async def remove_member(user_id: uuid.UUID, ctx: OrgCtx, session: SessionDep) -> Response:
    # Anyone may remove themselves (leave); removing others needs member-management rights.
    # The service enforces the role hierarchy.
    await member_service.remove_member(session, ctx, user_id)
    return Response(status_code=204)


# ---------- invitations ----------


@router.post("/{org_id}/invitations", response_model=InvitationCreated, status_code=201)
async def create_invitation(
    body: InvitationCreate, ctx: CanManageMembers, session: SessionDep
) -> InvitationCreated:
    invitation, link = await invitation_service.create_invitation(
        session, ctx, str(body.email), body.role
    )
    return InvitationCreated(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation_service.status_of(invitation),
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invite_url=link,
    )


@router.get("/{org_id}/invitations", response_model=Page[InvitationRead])
async def list_invitations(
    ctx: CanManageMembers,
    session: SessionDep,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> Page[InvitationRead]:
    rows, total = await invitation_repo.list_for_org(session, ctx.org_id, limit, offset)
    items = [
        InvitationRead(
            id=inv.id,
            email=inv.email,
            role=inv.role,
            status=invitation_service.status_of(inv),
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )
        for inv in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.delete("/{org_id}/invitations/{invitation_id}", status_code=204, response_class=Response)
async def revoke_invitation(
    invitation_id: uuid.UUID, ctx: CanManageMembers, session: SessionDep
) -> Response:
    await invitation_service.revoke_invitation(session, ctx, invitation_id)
    return Response(status_code=204)
