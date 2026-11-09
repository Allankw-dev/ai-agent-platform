import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    TenantMixin,
    UUIDPrimaryKeyMixin,
    json_object,
    now_column,
    tenant_fk,
)


class UsageRecord(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """One row per model call, used for billing, quotas and analytics."""

    __tablename__ = "usage_records"

    run_id: Mapped[uuid.UUID | None]
    agent_id: Mapped[uuid.UUID | None]
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default=text("0"))
    occurred_at: Mapped[datetime] = now_column()

    __table_args__ = (
        tenant_fk("run_id", "agent_runs"),
        tenant_fk("agent_id", "agents"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_non_negative"),
        Index("ix_usage_records_org_id_occurred_at", "org_id", "occurred_at"),
    )


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only security log. The runtime DB role can INSERT and SELECT, never UPDATE/DELETE."""

    __tablename__ = "audit_logs"

    # Deliberately NOT a foreign key: the log must outlive the organization it describes and
    # keep pointing at it, which a FK (even ON DELETE SET NULL) would not allow.
    org_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = json_object()
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (Index("ix_audit_logs_org_id_created_at", "org_id", "created_at"),)
