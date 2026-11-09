import re
import secrets
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.errors import ApiError
from app.db.tenancy import use_tenant
from app.models.enums import OrgRole
from app.models.identity import Organization, OrganizationMember, User
from app.repositories import members as member_repo
from app.repositories import organizations as org_repo
from app.services import audit


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return slug if len(slug) >= 2 else "org"


async def create_organization(
    session: AsyncSession, user: User, name: str, slug: str | None
) -> Organization:
    """Create an organization and make `user` its owner, in one transaction."""
    org_id = uuid.uuid4()
    # The new organization is the context for this transaction so Row Level Security lets the
    # creator insert it and then read it back.
    await use_tenant(session, user_id=user.id, org_id=org_id)

    if slug:
        candidates = [slug]
    else:
        base = slugify(name)
        candidates = [base, *(f"{base}-{secrets.token_hex(2)}" for _ in range(5))]

    organization: Organization | None = None
    for candidate in candidates:
        try:
            async with session.begin_nested():
                organization = Organization(
                    id=org_id, name=name, slug=candidate, created_by_id=user.id
                )
                session.add(organization)
                await session.flush()
            break
        except IntegrityError:
            organization = None
    if organization is None:
        raise ApiError(409, "slug_taken", "That URL name is already in use.")

    session.add(OrganizationMember(org_id=org_id, user_id=user.id, role=OrgRole.OWNER))
    await session.flush()
    await audit.record(
        session,
        org_id=org_id,
        actor_id=user.id,
        action="organization.created",
        resource_type="organization",
        resource_id=org_id,
        details={"name": name, "slug": organization.slug},
    )
    await session.commit()
    return organization


async def rename_organization(session: AsyncSession, ctx: OrgContext, name: str) -> Organization:
    organization = await org_repo.get(session, ctx.org_id)
    if organization is None:  # pragma: no cover - membership was just verified
        raise ApiError(404, "organization_not_found", "Organization not found.")
    previous = organization.name
    organization.name = name
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="organization.updated",
        resource_type="organization",
        resource_id=ctx.org_id,
        details={"from": previous, "to": name},
    )
    await session.commit()
    return organization


async def delete_organization(session: AsyncSession, ctx: OrgContext) -> None:
    organization = await org_repo.get(session, ctx.org_id)
    if organization is None:  # pragma: no cover - membership was just verified
        raise ApiError(404, "organization_not_found", "Organization not found.")
    # The organization will be gone afterwards, so the entry records what it was.
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="organization.deleted",
        resource_type="organization",
        resource_id=ctx.org_id,
        details={
            "name": organization.name,
            "slug": organization.slug,
            "member_count": await member_repo.count_members(session, ctx.org_id),
        },
    )
    await org_repo.delete_by_id(session, ctx.org_id)
    await session.commit()
