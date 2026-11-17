"""Stored (encrypted) credentials. Only app/services/credentials.py uses this module."""

import uuid

from sqlalchemy import delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CredentialKind
from app.models.integrations import Credential


async def get_for_integration(
    session: AsyncSession, org_id: uuid.UUID, integration_id: uuid.UUID
) -> Credential | None:
    return await session.scalar(
        select(Credential).where(
            Credential.org_id == org_id, Credential.integration_id == integration_id
        )
    )


async def upsert(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    integration_id: uuid.UUID,
    kind: CredentialKind,
    encrypted_payload: bytes,
    key_version: int,
    set_by_id: uuid.UUID | None,
) -> bool:
    """Save the integration's one credential. Returns True if it replaced an existing one."""
    values = {
        "kind": kind,
        "encrypted_payload": encrypted_payload,
        "key_version": key_version,
        "set_by_id": set_by_id,
    }
    inserted = await session.scalar(
        pg_insert(Credential)
        .values(org_id=org_id, integration_id=integration_id, **values)
        .on_conflict_do_update(
            index_elements=[Credential.integration_id],
            set_={**values, "updated_at": func.now()},
        )
        # xmax is 0 only on a freshly inserted row, so this tells an insert from a replacement.
        .returning(literal_column("(xmax = 0)").label("inserted"))
    )
    return not bool(inserted)


async def remove(session: AsyncSession, org_id: uuid.UUID, integration_id: uuid.UUID) -> bool:
    result = await session.execute(
        delete(Credential)
        .where(Credential.org_id == org_id, Credential.integration_id == integration_id)
        .returning(Credential.id)
    )
    return result.first() is not None
