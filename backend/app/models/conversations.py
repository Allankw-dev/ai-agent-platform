import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_column,
    now_column,
    tenant_fk,
)
from app.models.enums import MessageRole


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "conversations"

    agent_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (
        tenant_fk("agent_id", "agents"),
        UniqueConstraint("id", "org_id", name="uq_conversations_id_org_id"),
    )


class Message(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    run_id: Mapped[uuid.UUID | None]
    role: Mapped[MessageRole] = mapped_column(enum_column(MessageRole, "role"))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (
        tenant_fk("conversation_id", "conversations", ondelete="CASCADE"),
        tenant_fk("run_id", "agent_runs"),
    )
