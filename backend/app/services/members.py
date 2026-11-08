import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.errors import ApiError
from app.core.permissions import Permission, can_assign, can_manage, has_permission
from app.models.enums import OrgRole
from app.repositories import members as member_repo
from app.services import audit

_NOT_FOUND = ApiError(404, "member_not_found", "Member not found.")


def _insufficient() -> ApiError:
    return ApiError(403, "insufficient_role", "Your role does not allow this change.")


async def change_role(
    session: AsyncSession, ctx: OrgContext, target_user_id: uuid.UUID, new_role: OrgRole
) -> OrgRole:
    if target_user_id == ctx.user.id:
        raise ApiError(403, "cannot_change_own_role", "You cannot change your own role.")
    target = await member_repo.get(session, ctx.org_id, target_user_id)
    if target is None:
        raise _NOT_FOUND
    if not can_manage(ctx.role, target.role) or not can_assign(ctx.role, new_role):
        raise _insufficient()
    if (
        target.role is OrgRole.OWNER
        and new_role is not OrgRole.OWNER
        and await member_repo.count_owners(session, ctx.org_id) <= 1
    ):
        raise ApiError(409, "last_owner", "An organization must keep at least one owner.")

    previous = target.role
    target.role = new_role
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="member.role_changed",
        resource_type="user",
        resource_id=target_user_id,
        details={"from": previous.value, "to": new_role.value},
    )
    await session.commit()
    return new_role


async def remove_member(session: AsyncSession, ctx: OrgContext, target_user_id: uuid.UUID) -> None:
    """Remove a member, or let someone leave (removing themselves)."""
    target = await member_repo.get(session, ctx.org_id, target_user_id)
    if target is None:
        raise _NOT_FOUND
    leaving = target_user_id == ctx.user.id
    if not leaving:
        if not has_permission(ctx.role, Permission.MEMBERS_MANAGE):
            raise ApiError(403, "forbidden", "Your role does not allow this action.")
        if not can_manage(ctx.role, target.role):
            raise _insufficient()
    if target.role is OrgRole.OWNER and await member_repo.count_owners(session, ctx.org_id) <= 1:
        raise ApiError(409, "last_owner", "An organization must keep at least one owner.")

    await member_repo.delete_member(session, ctx.org_id, target_user_id)
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="member.left" if leaving else "member.removed",
        resource_type="user",
        resource_id=target_user_id,
        details={"role": target.role.value},
    )
    await session.commit()
