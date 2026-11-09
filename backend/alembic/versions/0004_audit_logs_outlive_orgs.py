"""audit logs keep their organization id after the organization is deleted

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08

audit_logs.org_id was a foreign key with ON DELETE SET NULL, so deleting an organization
detached its whole history from it. The column is now a plain indexed id: audit rows outlive the
organization and keep pointing at it. Tenants still cannot read them (the row policy only shows
rows of the organization in the current context, and nobody can act within a deleted one).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_audit_logs_org_id_organizations"


def upgrade() -> None:
    op.drop_constraint(FK_NAME, "audit_logs", type_="foreignkey")


def downgrade() -> None:
    # Rows of deleted organizations would violate the restored foreign key, so detach them.
    op.execute(
        "UPDATE audit_logs SET org_id = NULL "
        "WHERE org_id IS NOT NULL AND org_id NOT IN (SELECT id FROM organizations)"
    )
    op.create_foreign_key(
        FK_NAME, "audit_logs", "organizations", ["org_id"], ["id"], ondelete="SET NULL"
    )
