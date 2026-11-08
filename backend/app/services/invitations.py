import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.permissions import can_assign
from app.db.tenancy import use_tenant
from app.models.enums import OrgRole
from app.models.identity import Organization, OrganizationMember, User
from app.models.invitations import OrganizationInvitation as Invitation
from app.repositories import invitations as invitation_repo
from app.repositories import members as member_repo
from app.repositories import organizations as org_repo
from app.services import audit


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def status_of(invitation: Invitation) -> str:
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.expires_at <= datetime.now(UTC):
        return "expired"
    return "pending"


async def create_invitation(
    session: AsyncSession, ctx: OrgContext, email: str, role: OrgRole
) -> tuple[Invitation, str]:
    """Create an invitation. Returns it with the one-time link (the token is never stored)."""
    if not can_assign(ctx.role, role):
        raise ApiError(403, "insufficient_role", "Your role cannot invite someone to that role.")
    email = email.strip().lower()
    if await member_repo.email_is_member(session, ctx.org_id, email):
        raise ApiError(409, "already_member", "That person is already a member.")

    settings = get_settings()
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        org_id=ctx.org_id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        invited_by_id=ctx.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.invitation_ttl_days),
    )
    await invitation_repo.expire_stale(session, ctx.org_id, email)
    try:
        async with session.begin_nested():
            session.add(invitation)
            await session.flush()
    except IntegrityError as exc:
        raise ApiError(
            409, "invitation_pending", "There is already a pending invitation for that email."
        ) from exc

    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="invitation.created",
        resource_type="invitation",
        resource_id=invitation.id,
        details={"email": email, "role": role.value},
    )
    await session.commit()
    link = f"{settings.frontend_url.rstrip('/')}/invite/{token}"
    return invitation, link


async def revoke_invitation(
    session: AsyncSession, ctx: OrgContext, invitation_id: uuid.UUID
) -> None:
    invitation = await invitation_repo.get(session, ctx.org_id, invitation_id)
    if invitation is None:
        raise ApiError(404, "invitation_not_found", "Invitation not found.")
    if status_of(invitation) != "pending":
        raise ApiError(409, "invitation_not_pending", "Only pending invitations can be revoked.")
    invitation.revoked_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="invitation.revoked",
        resource_type="invitation",
        resource_id=invitation_id,
    )
    await session.commit()


async def accept_invitation(
    session: AsyncSession, user: User, token: str
) -> tuple[Organization, OrgRole]:
    # Holding the token lets the database show us this one invitation, nothing else.
    await use_tenant(session, user_id=user.id, invite_hash=hash_token(token))
    invitation = await invitation_repo.get_by_token_hash(session, hash_token(token))
    if invitation is None:
        raise ApiError(404, "invitation_not_found", "This invitation link is not valid.")

    state = status_of(invitation)
    if state == "expired":
        raise ApiError(410, "invitation_expired", "This invitation has expired.")
    if state != "pending":
        raise ApiError(410, "invitation_not_pending", "This invitation is no longer valid.")
    if invitation.email.lower() != user.email.lower():
        raise ApiError(
            403,
            "invitation_email_mismatch",
            "This invitation was sent to a different email address.",
        )

    # From here the invitation's organization is the context (the token proved the right to it).
    org_id, role = invitation.org_id, invitation.role
    await use_tenant(session, user_id=user.id, org_id=org_id)
    if await member_repo.get_role(session, org_id, user.id) is not None:
        raise ApiError(409, "already_member", "You are already a member of this organization.")
    if not await invitation_repo.claim(session, invitation.id):
        raise ApiError(410, "invitation_not_pending", "This invitation is no longer valid.")

    session.add(OrganizationMember(org_id=org_id, user_id=user.id, role=role))
    await session.flush()
    await audit.record(
        session,
        org_id=org_id,
        actor_id=user.id,
        action="invitation.accepted",
        resource_type="invitation",
        resource_id=invitation.id,
        details={"role": role.value},
    )
    organization = await org_repo.get(session, org_id)
    await session.commit()
    if organization is None:  # pragma: no cover - the invitation's FK guarantees it exists
        raise ApiError(404, "organization_not_found", "Organization not found.")
    return organization, role
