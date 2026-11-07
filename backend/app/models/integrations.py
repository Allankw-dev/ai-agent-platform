import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_column,
    json_object,
    nullable_timestamp,
    tenant_fk,
)
from app.models.enums import CredentialKind, IntegrationProvider, IntegrationStatus


class Integration(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A connected external account (e.g. a Slack workspace). Non-secret config only."""

    __tablename__ = "integrations"

    provider: Mapped[IntegrationProvider] = mapped_column(
        enum_column(IntegrationProvider, "provider")
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[IntegrationStatus] = mapped_column(
        enum_column(IntegrationStatus, "status"), server_default=IntegrationStatus.ACTIVE.value
    )
    config: Mapped[dict[str, Any]] = json_object()
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_integrations_id_org_id"),
        UniqueConstraint("org_id", "provider", "name", name="uq_integrations_org_id_provider_name"),
    )


class Credential(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Encrypted secret for an integration. The API must never return this payload."""

    __tablename__ = "credentials"

    integration_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[CredentialKind] = mapped_column(enum_column(CredentialKind, "kind"))
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    expires_at: Mapped[datetime | None] = nullable_timestamp()

    __table_args__ = (tenant_fk("integration_id", "integrations", ondelete="CASCADE"),)
