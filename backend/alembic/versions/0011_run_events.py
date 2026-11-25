"""run events: an append-only log of what happened to a run

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-24

Phase 5A.
- run_events: one row per change to a run, numbered per run (seq). Powers live streaming with
  reconnect-by-sequence and replay. Rows carry ids and statuses only, never tool arguments or
  output.
- agent_runs.event_seq: the counter behind seq. An event takes the next number with a single
  atomic UPDATE, so numbers are gap-free per run even with two writers.
- Row Level Security like every tenant table, but append-only like audit_logs: the runtime role
  can read and insert, never update or delete.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG = "app_current_org_id()"
EVENT_TYPES = (
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


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("event_seq", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_table(
        "run_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                *EVENT_TYPES,
                name="type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_run_events_seq_positive")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_run_events_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "org_id"],
            ["agent_runs.id", "agent_runs.org_id"],
            name=op.f("fk_run_events_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_events")),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_events_run_id_seq"),
    )
    op.create_index(op.f("ix_run_events_org_id"), "run_events", ["org_id"], unique=False)

    # Row Level Security (see docs/tenancy.md): readable and insertable inside the current
    # organization only. There is deliberately no UPDATE or DELETE policy, and the privileges
    # are revoked as well, so the log cannot be rewritten by the application.
    op.execute("ALTER TABLE run_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE run_events FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY run_events_select ON run_events FOR SELECT USING (org_id = {ORG})")
    op.execute(
        f"CREATE POLICY run_events_insert ON run_events FOR INSERT WITH CHECK (org_id = {ORG})"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_app') THEN
                GRANT SELECT, INSERT ON run_events TO agent_app;
                REVOKE UPDATE, DELETE ON run_events FROM agent_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("run_events")  # drops its policies and indexes with it
    op.drop_column("agent_runs", "event_seq")
