"""Gives tool handlers the integration their grant points at, secret included.

This is one of the only two places that touch a saved secret (the other is the credentials
service it calls). It runs in the worker, at the moment a tool call executes, and hands the secret
to the handler in an object whose repr hides it. Nothing here logs or stores it.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.vault import VaultDecryptError, VaultNotConfiguredError
from app.db.tenancy import use_tenant
from app.models.enums import IntegrationProvider, IntegrationStatus
from app.repositories import integrations as integration_repo
from app.services import credentials as credential_service
from app.tools.base import ResolvedIntegration, ToolError

log = structlog.get_logger()


class DatabaseIntegrationAccess:
    """Loads an integration (and decrypts its secret) for one organization's tool call."""

    def __init__(self, maker: async_sessionmaker[AsyncSession], org_id: uuid.UUID) -> None:
        self._maker = maker
        self._org_id = org_id

    async def resolve(
        self, integration_id: object, provider: IntegrationProvider
    ) -> ResolvedIntegration:
        try:
            wanted = uuid.UUID(str(integration_id))
        except ValueError:
            raise ToolError(
                "This tool is not connected to an integration. Ask an admin to choose one in "
                "the agent's settings."
            ) from None

        async with self._maker() as session:
            await use_tenant(session, org_id=self._org_id)
            integration = await integration_repo.get(session, self._org_id, wanted)
            if integration is None:
                raise ToolError(
                    "The integration for this tool no longer exists. Ask an admin to choose "
                    "another in the agent's settings."
                )
            if integration.provider is not provider:
                raise ToolError("The integration for this tool is not the right type.")
            if integration.status is not IntegrationStatus.ACTIVE:
                raise ToolError(
                    f"The integration “{integration.name}” is disabled. An admin can enable it "
                    "in the Integrations tab."
                )
            try:
                secret = await credential_service.reveal_secret(session, self._org_id, wanted)
            except VaultNotConfiguredError:
                raise ToolError(
                    "Saved credentials cannot be used because the server has no encryption key."
                ) from None
            except VaultDecryptError:
                log.warning("integration.secret_unreadable", integration_id=str(wanted))
                raise ToolError(
                    f"The saved secret for “{integration.name}” could not be used. An admin "
                    "should save it again."
                ) from None
            return ResolvedIntegration(
                id=integration.id,
                provider=integration.provider,
                name=integration.name,
                config=dict(integration.config),
                secret=secret,
            )
