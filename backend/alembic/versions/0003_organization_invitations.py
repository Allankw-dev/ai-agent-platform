"""organization invitations

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07 20:16:13.810071
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ORG = "app_current_org_id()"


def _secure_table() -> None:
    """Row Level Security and privileges for the new table (see docs/tenancy.md)."""
    op.execute(
        """
        CREATE FUNCTION app_current_invite_hash() RETURNS text
        LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.invite_hash', true), '') $$
        """
    )
    table = "organization_invitations"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    # Visible inside the organization, or to whoever holds the one-time token (so a person can
    # accept an invitation before they belong to the organization).
    op.execute(
        f"CREATE POLICY invitations_select ON {table} FOR SELECT "
        f"USING (org_id = {ORG} OR token_hash = app_current_invite_hash())"
    )
    op.execute(
        f"CREATE POLICY invitations_insert ON {table} FOR INSERT WITH CHECK (org_id = {ORG})"
    )
    op.execute(
        f"CREATE POLICY invitations_update ON {table} FOR UPDATE "
        f"USING (org_id = {ORG}) WITH CHECK (org_id = {ORG})"
    )
    op.execute(f"CREATE POLICY invitations_delete ON {table} FOR DELETE USING (org_id = {ORG})")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO agent_app;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "admin",
                "developer",
                "member",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("role <> 'owner'", name=op.f("ck_organization_invitations_not_owner")),
        sa.ForeignKeyConstraint(
            ["invited_by_id"],
            ["users.id"],
            name=op.f("fk_organization_invitations_invited_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_organization_invitations_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_organization_invitations_token_hash")),
    )
    op.create_index(
        op.f("ix_organization_invitations_org_id"),
        "organization_invitations",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "uq_organization_invitations_pending",
        "organization_invitations",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )

    _secure_table()


def downgrade() -> None:
    op.drop_index(
        "uq_organization_invitations_pending",
        table_name="organization_invitations",
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.drop_index(op.f("ix_organization_invitations_org_id"), table_name="organization_invitations")
    op.drop_table("organization_invitations")
    op.execute("DROP FUNCTION app_current_invite_hash()")
