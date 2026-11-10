import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_column,
    json_object,
    now_column,
    nullable_timestamp,
    tenant_fk,
)
from app.models.enums import AgentStatus, IntegrationProvider, LLMProvider


class Tool(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Global tool catalog (not tenant-owned). Seeded by migrations, read-only at runtime."""

    __tablename__ = "tools"

    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provider: Mapped[IntegrationProvider | None] = mapped_column(
        enum_column(IntegrationProvider, "provider")
    )
    is_sensitive: Mapped[bool] = mapped_column(server_default=text("false"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, server_default=text("30"))

    __table_args__ = (CheckConstraint("timeout_seconds > 0", name="timeout_positive"),)


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AgentStatus] = mapped_column(
        enum_column(AgentStatus, "status"), server_default=AgentStatus.DRAFT.value
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "agent_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_agents_current_version_id_agent_versions",
        )
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = nullable_timestamp()

    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_agents_id_org_id"),
        # Names are unique per organization among non-deleted agents.
        Index(
            "uq_agents_org_id_name_active",
            "org_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class AgentVersion(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Immutable snapshot of an agent's configuration. Rollback = point the agent at an old one."""

    __tablename__ = "agent_versions"

    agent_id: Mapped[uuid.UUID] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(Integer)
    system_instructions: Mapped[str] = mapped_column(Text)
    objectives: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[LLMProvider] = mapped_column(
        enum_column(LLMProvider, "provider"), server_default=LLMProvider.GEMINI.value
    )
    model: Mapped[str] = mapped_column(String(100))
    model_params: Mapped[dict[str, Any]] = json_object()
    memory_config: Mapped[dict[str, Any]] = json_object()
    limits: Mapped[dict[str, Any]] = json_object()
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (
        tenant_fk("agent_id", "agents"),
        UniqueConstraint("id", "org_id", name="uq_agent_versions_id_org_id"),
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_id_version"),
        CheckConstraint("version > 0", name="version_positive"),
    )


class AgentTool(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Which tools a given agent version may use, and whether each needs human approval."""

    __tablename__ = "agent_tools"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(index=True)
    tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tools.id"), index=True)
    requires_approval: Mapped[bool] = mapped_column(server_default=text("false"))
    config: Mapped[dict[str, Any]] = json_object()

    __table_args__ = (
        tenant_fk("agent_version_id", "agent_versions", ondelete="CASCADE"),
        UniqueConstraint(
            "agent_version_id", "tool_id", name="uq_agent_tools_agent_version_id_tool_id"
        ),
    )
