import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrgRole
from app.models.identity import Organization, OrganizationMember


async def get(session: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    return await session.get(Organization, org_id)


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[tuple[Organization, OrgRole]], int]:
    base = (
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(base.order_by(Organization.name).limit(limit).offset(offset))
    return [(org, role) for org, role in rows.all()], int(total or 0)


async def delete_by_id(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(delete(Organization).where(Organization.id == org_id))
