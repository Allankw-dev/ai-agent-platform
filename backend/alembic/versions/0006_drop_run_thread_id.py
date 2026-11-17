"""drop agent_runs.thread_id

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16

The column was meant to link a run to a persisted LangGraph checkpoint. Nothing ever read or wrote
it, and Phase 4 pauses runs with its own checkpoint saved on the run (docs/phase4-design.md,
decision 6), so it is removed instead of left behind as a misleading column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("agent_runs", "thread_id")


def downgrade() -> None:
    op.add_column("agent_runs", sa.Column("thread_id", sa.String(length=100), nullable=True))
