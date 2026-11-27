"""crash recovery: attempts, heartbeats, and a unique key per tool call

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-26

Phase 5C.
- agent_runs.attempt: 1 for the first stretch of work, +1 each time a run is recovered after its
  worker died. Every write a worker makes is conditional on its own attempt number (fencing), so a
  worker that was only stalled cannot go on writing after a new one has taken over.
- agent_runs.heartbeat_at: written every few seconds by the worker that holds the run. A running run
  whose heartbeat has stopped has lost its worker.
- run_steps.call_key: names one tool call of one model reply ("2.0" is the first call of the second
  reply). It is unique per run, so a tool call can be started at most once however many times a
  task is delivered, and a call that already finished is replayed from its recorded result instead
  of being run again.
- run_events gains the type 'run.recovered'.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_EVENT_TYPES = (
    "run.queued",
    "run.started",
    "step.started",
    "step.finished",
    "approval.requested",
    "approval.decided",
    "run.awaiting_approval",
    "run.resumed",
    "run.finished",
    "run.cancelled",
)
NEW_EVENT_TYPES = (*OLD_EVENT_TYPES, "run.recovered")


def _in_list(values: Sequence[str]) -> str:
    return "type IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "agent_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(op.f("ck_agent_runs_attempt_positive"), "agent_runs", "attempt >= 1")

    op.add_column("run_steps", sa.Column("call_key", sa.String(length=40), nullable=True))
    op.create_index(
        "uq_run_steps_run_id_call_key",
        "run_steps",
        ["run_id", "call_key"],
        unique=True,
        postgresql_where=sa.text("call_key IS NOT NULL"),
    )

    op.drop_constraint(op.f("ck_run_events_type"), "run_events", type_="check")
    op.create_check_constraint(op.f("ck_run_events_type"), "run_events", _in_list(NEW_EVENT_TYPES))


def downgrade() -> None:
    op.execute("DELETE FROM run_events WHERE type = 'run.recovered'")
    op.drop_constraint(op.f("ck_run_events_type"), "run_events", type_="check")
    op.create_check_constraint(op.f("ck_run_events_type"), "run_events", _in_list(OLD_EVENT_TYPES))

    op.drop_index("uq_run_steps_run_id_call_key", table_name="run_steps")
    op.drop_column("run_steps", "call_key")

    op.drop_constraint(op.f("ck_agent_runs_attempt_positive"), "agent_runs", type_="check")
    op.drop_column("agent_runs", "heartbeat_at")
    op.drop_column("agent_runs", "attempt")
