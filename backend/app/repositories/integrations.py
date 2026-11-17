import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import IntegrationProvider
from app.models.identity import User
from app.models.integrations import Credential, Integration


@dataclass(frozen=True)
class IntegrationRow:
    """An integration plus what is known *about* its secret (never the secret)."""

    integration: Integration
    has_credential: bool
    credential_updated_at: datetime | None
    credential_set_by_id: uuid.UUID | None
    credential_set_by_name: str | None


def _with_credential_facts() -> Any:
    """Each row: integration, credential id, credential updated_at, who set it, their name/email."""
    return (
        select(
            Integration,
            Credential.id,
            Credential.updated_at,
            Credential.set_by_id,
            User.full_name,
            User.email,
        )
        .outerjoin(Credential, Credential.integration_id == Integration.id)
        .outerjoin(User, User.id == Credential.set_by_id)
    )


def _row(values: Any) -> IntegrationRow:
    integration, credential_id, updated_at, set_by_id, full_name, email = values
    return IntegrationRow(
        integration=integration,
        has_credential=credential_id is not None,
        credential_updated_at=updated_at,
        credential_set_by_id=set_by_id,
        credential_set_by_name=(full_name or email) if set_by_id else None,
    )


async def get(
    session: AsyncSession, org_id: uuid.UUID, integration_id: uuid.UUID, *, lock: bool = False
) -> Integration | None:
    statement = select(Integration).where(
        Integration.org_id == org_id, Integration.id == integration_id
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def get_row(
    session: AsyncSession, org_id: uuid.UUID, integration_id: uuid.UUID
) -> IntegrationRow | None:
    result = await session.execute(
        _with_credential_facts().where(
            Integration.org_id == org_id, Integration.id == integration_id
        )
    )
    values = result.first()
    return _row(values) if values else None


async def list_for_org(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    provider: IntegrationProvider | None,
    limit: int,
    offset: int,
) -> tuple[list[IntegrationRow], int]:
    count = select(func.count()).select_from(Integration).where(Integration.org_id == org_id)
    statement = _with_credential_facts().where(Integration.org_id == org_id)
    if provider is not None:
        count = count.where(Integration.provider == provider)
        statement = statement.where(Integration.provider == provider)
    total = await session.scalar(count)
    result = await session.execute(
        statement.order_by(Integration.name, Integration.id).limit(limit).offset(offset)
    )
    return [_row(values) for values in result.all()], int(total or 0)
