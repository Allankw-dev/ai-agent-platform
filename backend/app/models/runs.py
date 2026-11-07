import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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
    UUIDPrimaryKeyMixin,
    enum_column,
    now_column,
    nullable_timestamp,
    tenant_fk,
)
from app.models.enums import ApprovalStatus, RunStatus, RunTrigger, StepStatus, StepType


class AgentRun(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "agent_runs"

    agent_id: Mapped[uuid.UUID] = mapped_column(index=True)
    agent_version_id: Mapped[uuid.UUID]
    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "status"), server_default=RunStatus.QUEUED.value
    )
    trigger: Mapped[RunTrigger] = mapped_column(enum_column(RunTrigger, "trigger"))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    # Links the run to its persisted LangGraph checkpoint (used to resume after approval).
    thread_id: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default=text("0"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = now_column()
    started_at: Mapped[datetime | None] = nullable_timestamp()
    finished_at: Mapped[datetime | None] = nullable_timestamp()

    __table_args__ = (
        tenant_fk("agent_id", "agents"),
        tenant_fk("agent_version_id", "agent_versions"),
        UniqueConstraint("id", "org_id", name="uq_agent_runs_id_org_id"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_agent_runs_org_id_idempotency_key"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_non_negative"),
        Index("ix_agent_runs_org_id_created_at", "org_id", "created_at"),
        Index("ix_agent_runs_org_id_status", "org_id", "status"),
    )


class RunStep(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "run_steps"

    run_id: Mapped[uuid.UUID] = mapped_column(index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[StepType] = mapped_column(enum_column(StepType, "step_type"))
    status: Mapped[StepStatus] = mapped_column(
        enum_column(StepStatus, "status"), server_default=StepStatus.RUNNING.value
    )
    name: Mapped[str | None] = mapped_column(String(200))
    # Stored as text (not an FK) so history survives changes to the tool catalog.
    tool_key: Mapped[str | None] = mapped_column(String(100))
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    started_at: Mapped[datetime] = now_column()
    finished_at: Mapped[datetime | None] = nullable_timestamp()

    __table_args__ = (
        tenant_fk("run_id", "agent_runs", ondelete="CASCADE"),
        UniqueConstraint("id", "org_id", name="uq_run_steps_id_org_id"),
        UniqueConstraint("run_id", "sequence", name="uq_run_steps_run_id_sequence"),
        CheckConstraint("sequence >= 0", name="sequence_non_negative"),
    )


class Approval(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "approvals"

    run_id: Mapped[uuid.UUID] = mapped_column(index=True)
    run_step_id: Mapped[uuid.UUID | None]
    tool_key: Mapped[str] = mapped_column(String(100))
    proposed_input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reasoning_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_column(ApprovalStatus, "status"), server_default=ApprovalStatus.PENDING.value
    )
    requested_at: Mapped[datetime] = now_column()
    expires_at: Mapped[datetime | None] = nullable_timestamp()
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = nullable_timestamp()
    decision_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        tenant_fk("run_id", "agent_runs", ondelete="CASCADE"),
        tenant_fk("run_step_id", "run_steps"),
        Index("ix_approvals_org_id_status", "org_id", "status"),
    )
