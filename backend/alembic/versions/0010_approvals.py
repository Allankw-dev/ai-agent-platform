"""approvals: pause and resume

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-20

Phase 4D.
- agent_runs.checkpoint: the saved state of a run that is waiting for a person.
- agent_runs.last_resumed_at: when the current stretch of work began after a pause, so waiting
  time is not counted against the run's time limit or mistaken for a dead worker.
- run_steps.status gains 'awaiting_approval' (a tool call waiting for a decision).
- approvals.status gains 'cancelled' (the run ended before anyone decided).
- A run waits on one decision at a time: at most one pending approval per run.
- An index for the approvals inbox, newest first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STEP_STATUSES = ("running", "succeeded", "failed", "skipped")
NEW_STEP_STATUSES = ("running", "awaiting_approval", "succeeded", "failed", "skipped")
OLD_APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired")
NEW_APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "cancelled")


def _in_list(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _swap_check(table: str, name: str, column: str, values: Sequence[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, _in_list(column, values))


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("checkpoint", postgresql.JSONB(), nullable=True))
    op.add_column(
        "agent_runs", sa.Column("last_resumed_at", sa.DateTime(timezone=True), nullable=True)
    )
    _swap_check("run_steps", "ck_run_steps_status", "status", NEW_STEP_STATUSES)
    _swap_check("approvals", "ck_approvals_status", "status", NEW_APPROVAL_STATUSES)
    op.create_index(
        "uq_approvals_one_pending_per_run",
        "approvals",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_approvals_org_id_requested_at", "approvals", ["org_id", "requested_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_org_id_requested_at", table_name="approvals")
    op.drop_index("uq_approvals_one_pending_per_run", table_name="approvals")
    # Rows using the new values are folded into the closest old value before the rule tightens.
    op.execute("UPDATE approvals SET status = 'expired' WHERE status = 'cancelled'")
    op.execute("UPDATE run_steps SET status = 'skipped' WHERE status = 'awaiting_approval'")
    _swap_check("approvals", "ck_approvals_status", "status", OLD_APPROVAL_STATUSES)
    _swap_check("run_steps", "ck_run_steps_status", "status", OLD_STEP_STATUSES)
    op.drop_column("agent_runs", "last_resumed_at")
    op.drop_column("agent_runs", "checkpoint")
