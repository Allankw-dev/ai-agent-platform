import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.errors import ApiError
from app.models.enums import IntegrationProvider, IntegrationStatus
from app.models.integrations import Integration
from app.repositories import integrations as integration_repo
from app.repositories.integrations import IntegrationRow
from app.schemas.integration import (
    SUPPORTED_PROVIDERS,
    CredentialSet,
    IntegrationCreate,
    IntegrationRead,
    IntegrationUpdate,
    normalize_config,
)
from app.services import audit
from app.services import credentials as credential_service


def _not_found() -> ApiError:
    return ApiError(404, "integration_not_found", "Integration not found.")


def _name_taken() -> ApiError:
    return ApiError(
        409,
        "integration_name_taken",
        "An integration of that type with that name already exists.",
    )


def _read(row: IntegrationRow) -> IntegrationRead:
    integration = row.integration
    return IntegrationRead(
        id=integration.id,
        provider=integration.provider,
        name=integration.name,
        status=integration.status.value,
        config=integration.config,
        has_credential=row.has_credential,
        credential_set_by_id=row.credential_set_by_id,
        credential_set_by_name=row.credential_set_by_name,
        credential_updated_at=row.credential_updated_at,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


def _checked_config(provider: IntegrationProvider, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate the settings for the provider, turning problems into a clear 422."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ApiError(
            422,
            "provider_not_supported",
            f"The {provider.value} integration is not available yet.",
        )
    try:
        return normalize_config(provider, raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{error['loc'][0] if error['loc'] else 'config'}: "
            f"{error['msg'].removeprefix('Value error, ')}"
            for error in exc.errors(include_input=False)
        )
        raise ApiError(422, "invalid_integration_config", problems[:500]) from exc


async def _load(
    session: AsyncSession, ctx: OrgContext, integration_id: uuid.UUID
) -> IntegrationRow:
    row = await integration_repo.get_row(session, ctx.org_id, integration_id)
    if row is None:
        raise _not_found()
    return row


async def list_integrations(
    session: AsyncSession,
    ctx: OrgContext,
    *,
    provider: IntegrationProvider | None,
    limit: int,
    offset: int,
) -> tuple[list[IntegrationRead], int]:
    rows, total = await integration_repo.list_for_org(
        session, ctx.org_id, provider=provider, limit=limit, offset=offset
    )
    return [_read(row) for row in rows], total


async def get_integration(
    session: AsyncSession, ctx: OrgContext, integration_id: uuid.UUID
) -> IntegrationRead:
    return _read(await _load(session, ctx, integration_id))


async def create_integration(
    session: AsyncSession, ctx: OrgContext, body: IntegrationCreate
) -> IntegrationRead:
    config = _checked_config(body.provider, body.config)
    integration = Integration(
        org_id=ctx.org_id,
        provider=body.provider,
        name=body.name,
        status=IntegrationStatus.ACTIVE,
        config=config,
        created_by_id=ctx.user.id,
    )
    try:
        async with session.begin_nested():
            session.add(integration)
            await session.flush()
    except IntegrityError as exc:
        raise _name_taken() from exc
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="integration.created",
        resource_type="integration",
        resource_id=integration.id,
        details={"provider": body.provider.value, "name": body.name},
    )
    await session.commit()
    return _read(await _load(session, ctx, integration.id))


async def update_integration(
    session: AsyncSession, ctx: OrgContext, integration_id: uuid.UUID, body: IntegrationUpdate
) -> IntegrationRead:
    integration = await integration_repo.get(session, ctx.org_id, integration_id, lock=True)
    if integration is None:
        raise _not_found()

    changes: dict[str, Any] = {}
    if body.name is not None and body.name != integration.name:
        changes["name"] = {"from": integration.name, "to": body.name}
        integration.name = body.name
    if body.status is not None and body.status != integration.status.value:
        changes["status"] = {"from": integration.status.value, "to": body.status}
        integration.status = IntegrationStatus(body.status)
    if body.config is not None:
        config = _checked_config(integration.provider, body.config)
        if config != integration.config:
            changes["config"] = "updated"  # the settings are not secret, but keep the log short
            integration.config = config

    if changes:
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as exc:
            raise _name_taken() from exc
        await audit.record(
            session,
            org_id=ctx.org_id,
            actor_id=ctx.user.id,
            action="integration.updated",
            resource_type="integration",
            resource_id=integration.id,
            details=changes,
        )
    await session.commit()
    return _read(await _load(session, ctx, integration.id))


async def delete_integration(
    session: AsyncSession, ctx: OrgContext, integration_id: uuid.UUID
) -> None:
    integration = await integration_repo.get(session, ctx.org_id, integration_id, lock=True)
    if integration is None:
        raise _not_found()
    details = {"provider": integration.provider.value, "name": integration.name}
    await session.delete(integration)  # its credential goes with it (ON DELETE CASCADE)
    await session.flush()
    await audit.record(
        session,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="integration.deleted",
        resource_type="integration",
        resource_id=integration_id,
        details=details,
    )
    await session.commit()


async def set_credential(
    session: AsyncSession, ctx: OrgContext, integration_id: uuid.UUID, body: CredentialSet
) -> IntegrationRead:
    if await integration_repo.get(session, ctx.org_id, integration_id) is None:
        raise _not_found()
    await credential_service.save_secret(
        session, ctx, integration_id, body.secret.get_secret_value()
    )
    await session.commit()
    return _read(await _load(session, ctx, integration_id))


async def remove_credential(
    session: AsyncSession, ctx: OrgContext, integration_id: uuid.UUID
) -> None:
    if await integration_repo.get(session, ctx.org_id, integration_id) is None:
        raise _not_found()
    if not await credential_service.remove_secret(session, ctx, integration_id):
        raise ApiError(404, "credential_not_found", "This integration has no saved secret.")
    await session.commit()
