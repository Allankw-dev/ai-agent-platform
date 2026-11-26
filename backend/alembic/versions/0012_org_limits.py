"""organization limits and per-run reservations

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-25

Phase 5B.
- org_limits: one optional row per organization with its own concurrency and daily quotas. No row
  means the platform defaults (settings ORG_DEFAULT_*) apply.
- agent_runs.reserved_tokens / reserved_cost_usd: what a run set aside when it was created. They
  count against the organization's daily quota only while the run is open (queued, running or
  waiting for approval), so a run that ends in any way releases its reservation by itself.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG = "app_current_org_id()"


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("reserved_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "agent_runs",
        sa.Column("reserved_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
    )
    op.create_check_constraint(
        "ck_agent_runs_reservation_non_negative",
        "agent_runs",
        "reserved_tokens >= 0 AND (reserved_cost_usd IS NULL OR reserved_cost_usd >= 0)",
    )

    op.create_table(
        "org_limits",
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=False),
        sa.Column("daily_token_quota", sa.Integer(), nullable=False),
        sa.Column("daily_cost_quota_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "max_concurrent_runs >= 1", name=op.f("ck_org_limits_concurrency_positive")
        ),
        sa.CheckConstraint(
            "daily_token_quota >= 1000", name=op.f("ck_org_limits_token_quota_sane")
        ),
        sa.CheckConstraint(
            "daily_cost_quota_usd IS NULL OR daily_cost_quota_usd > 0",
            name=op.f("ck_org_limits_cost_quota_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_org_limits_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_org_limits_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_limits")),
        sa.UniqueConstraint("org_id", name="uq_org_limits_org_id"),
    )
    op.create_index(op.f("ix_org_limits_org_id"), "org_limits", ["org_id"], unique=False)

    op.execute("ALTER TABLE org_limits ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE org_limits FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON org_limits FOR ALL "
        f"USING (org_id = {ORG}) WITH CHECK (org_id = {ORG})"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON org_limits TO agent_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("org_limits")
    op.drop_constraint("ck_agent_runs_reservation_non_negative", "agent_runs", type_="check")
    op.drop_column("agent_runs", "reserved_cost_usd")
    op.drop_column("agent_runs", "reserved_tokens")
