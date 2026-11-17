"""one credential per integration, and who set it

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16

Phase 4A (credential vault):
- An integration has at most one secret, so "replace" is an update of that one row.
  The unique constraint on integration_id replaces the plain index that was there.
- credentials.set_by_id records who last saved the secret (the API shows "saved by X on <date>";
  it never shows the secret itself).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credentials", sa.Column("set_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_credentials_set_by_id_users"),
        "credentials",
        "users",
        ["set_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_index(op.f("ix_credentials_integration_id"), table_name="credentials")
    op.create_unique_constraint(
        op.f("uq_credentials_integration_id"), "credentials", ["integration_id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_credentials_integration_id"), "credentials", type_="unique")
    op.create_index(
        op.f("ix_credentials_integration_id"), "credentials", ["integration_id"], unique=False
    )
    op.drop_constraint(op.f("fk_credentials_set_by_id_users"), "credentials", type_="foreignkey")
    op.drop_column("credentials", "set_by_id")
