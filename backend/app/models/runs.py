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
from app.models.enums import (
    ApprovalStatus,
    RunEventType,
    RunStatus,
    RunTrigger,
    StepStatus,
    StepType,
)


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
    # While a run waits for a person: the saved state of the agent loop (see docs/approvals.md).
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # When the current stretch of work began after a pause. Waiting time is not work time, so the
    # orphan check and the time limit count from here, not from `started_at`.
    last_resumed_at: Mapped[datetime | None] = nullable_timestamp()
    # Counter behind run_events.seq: each event takes the next number with one atomic UPDATE, so
    # numbers are gap-free per run even with two writers (see repositories/run_events.py).
    event_seq: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # What this run set aside against the organization's daily quota when it was created (its
    # token budget, and its cost budget if it has one). It counts only while the run is open, so a
    # run that ends in any way releases it with no bookkeeping (see repositories/quotas.py).
    # 1 for the first stretch of work, +1 for each recovery after a lost worker. Every write by a
    # worker is conditional on its own attempt, so a worker that was merely stalled cannot go on
    # writing once another has taken over.
    attempt: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # Written every few seconds by the worker that holds the run (see engine/liveness.py).
    heartbeat_at: Mapped[datetime | None] = nullable_timestamp()
    reserved_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    reserved_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))

    __table_args__ = (
        tenant_fk("agent_id", "agents"),
        tenant_fk("agent_version_id", "agent_versions"),
        UniqueConstraint("id", "org_id", name="uq_agent_runs_id_org_id"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_agent_runs_org_id_idempotency_key"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_non_negative"),
        CheckConstraint(
            "reserved_tokens >= 0 AND (reserved_cost_usd IS NULL OR reserved_cost_usd >= 0)",
            name="reservation_non_negative",
        ),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
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
    # Names one tool call of one model reply ("2.0": the first call of the second reply). Unique
    # per run, so a call starts at most once however often a task is delivered, and a finished call
    # is replayed from its recorded result instead of being run again. Null for model calls.
    call_key: Mapped[str | None] = mapped_column(String(40))

    __table_args__ = (
        tenant_fk("run_id", "agent_runs", ondelete="CASCADE"),
        Index(
            "uq_run_steps_run_id_call_key",
            "run_id",
            "call_key",
            unique=True,
            postgresql_where=text("call_key IS NOT NULL"),
        ),
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
        Index("ix_approvals_org_id_requested_at", "org_id", "requested_at"),
        # A run waits on one person's decision at a time.
        Index(
            "uq_approvals_one_pending_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )


class RunEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Append-only log of what happened to a run, in order. Powers live streaming and replay.

    `data` holds ids, statuses and counts only: never tool arguments, tool output or message
    text, so an event can never leak what a step handled. Clients fetch the details separately.
    """

    __tablename__ = "run_events"

    run_id: Mapped[uuid.UUID]
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[RunEventType] = mapped_column(enum_column(RunEventType, "type"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (
        tenant_fk("run_id", "agent_runs", ondelete="CASCADE"),
        UniqueConstraint("run_id", "seq", name="uq_run_events_run_id_seq"),
        CheckConstraint("seq >= 1", name="seq_positive"),
    )
