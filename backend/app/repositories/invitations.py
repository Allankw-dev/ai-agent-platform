import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invitations import OrganizationInvitation as Invitation


async def get(
    session: AsyncSession, org_id: uuid.UUID, invitation_id: uuid.UUID
) -> Invitation | None:
    return await session.scalar(
        select(Invitation).where(Invitation.org_id == org_id, Invitation.id == invitation_id)
    )


async def get_by_token_hash(session: AsyncSession, token_hash: str) -> Invitation | None:
    return await session.scalar(select(Invitation).where(Invitation.token_hash == token_hash))


async def list_for_org(
    session: AsyncSession, org_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[Invitation], int]:
    base = select(Invitation).where(Invitation.org_id == org_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.scalars(
        base.order_by(Invitation.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows), int(total or 0)


async def expire_stale(session: AsyncSession, org_id: uuid.UUID, email: str) -> None:
    """Free the email for a new invitation by closing expired ones that are still 'open'."""
    await session.execute(
        update(Invitation)
        .where(
            Invitation.org_id == org_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at < datetime.now(UTC),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def claim(session: AsyncSession, invitation_id: uuid.UUID) -> bool:
    """Atomically mark an open invitation as accepted. False if someone else got there first."""
    result = await session.execute(
        update(Invitation)
        .where(
            Invitation.id == invitation_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(accepted_at=datetime.now(UTC))
        .returning(Invitation.id)
    )
    return result.first() is not None
