import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrgRole
from app.models.identity import OrganizationMember, User


async def get_role(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> OrgRole | None:
    return await session.scalar(
        select(OrganizationMember.role).where(
            OrganizationMember.org_id == org_id, OrganizationMember.user_id == user_id
        )
    )


async def get(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember | None:
    return await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org_id, OrganizationMember.user_id == user_id
        )
    )


async def list_with_users(
    session: AsyncSession, org_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[tuple[OrganizationMember, User]], int]:
    base = (
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.org_id == org_id)
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.order_by(OrganizationMember.created_at, User.email).limit(limit).offset(offset)
    )
    return [(member, user) for member, user in rows.all()], int(total or 0)


async def count_owners(session: AsyncSession, org_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count()).where(
            OrganizationMember.org_id == org_id, OrganizationMember.role == OrgRole.OWNER
        )
    )
    return int(count or 0)


async def email_is_member(session: AsyncSession, org_id: uuid.UUID, email: str) -> bool:
    found = await session.scalar(
        select(OrganizationMember.id)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.org_id == org_id, func.lower(User.email) == email.lower())
    )
    return found is not None


async def delete_member(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await session.execute(
        delete(OrganizationMember).where(
            OrganizationMember.org_id == org_id, OrganizationMember.user_id == user_id
        )
    )
