"""Saving, removing and (for tools only) reading an integration's secret.

This is the only module that decrypts a stored credential. The API never returns a secret:
`reveal_secret` is for server-side code that must act with it, such as a tool handler running in
the worker. Callers must not log the value, store it in a run step, or send it to a model, and
should pass tool output through `app.core.vault.redact_secret` before recording it.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.errors import ApiError
from app.core.vault import VaultNotConfiguredError, get_vault
from app.models.enums import CredentialKind
from app.repositories import credentials as credential_repo
from app.services import audit

log = structlog.get_logger()


def not_configured(exc: VaultNotConfiguredError) -> ApiError:
    return ApiError(503, "credentials_not_configured", str(exc))


async def save_secret(
    session: AsyncSession, ctx: OrgContext, integration_id: uuid.UUID, secret: str
) -> bool:
    """Encrypt and store the secret, replacing any existing one. Returns True if it replaced one.

    Runs inside the caller's transaction, and writes an audit entry that never contains the secret.
    """
    try:
        vault = get_vault()
    except VaultNotConfiguredError as exc:
        raise not_configured(exc) from exc
    payload, key_version = vault.encrypt(secret, org_id=ctx.org_id, integration_id=integration_id)
    replaced = await credential_repo.upsert(
        session,
        org_id=ctx.org_id,
        integration_id=integration_id,
        kind=CredentialKind.API_KEY,
        encrypted_payload=payload,
        key_version=key_version,
        set_by_id=ctx.user.id,
    )
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="credential.replaced" if replaced else "credential.added",
        resource_type="integration",
        resource_id=integration_id,
        details={"key_version": key_version},
    )
    return replaced


async def remove_secret(session: AsyncSession, ctx: OrgContext, integration_id: uuid.UUID) -> bool:
    """Delete the integration's secret. Returns False if none was saved."""
    removed = await credential_repo.remove(session, ctx.org_id, integration_id)
    if removed:
        await audit.record(
            session,
            org_id=ctx.org_id,
            actor_id=ctx.user.id,
            action="credential.removed",
            resource_type="integration",
            resource_id=integration_id,
        )
    return removed


async def reveal_secret(
    session: AsyncSession, org_id: uuid.UUID, integration_id: uuid.UUID
) -> str | None:
    """The decrypted secret, or None when the integration has none. Server-side use only.

    Raises VaultNotConfiguredError if the server has no key, and VaultDecryptError if the stored
    value does not belong to this organization and integration or has been tampered with.
    """
    credential = await credential_repo.get_for_integration(session, org_id, integration_id)
    if credential is None:
        return None
    return get_vault().decrypt(
        credential.encrypted_payload,
        credential.key_version,
        org_id=org_id,
        integration_id=integration_id,
    )
