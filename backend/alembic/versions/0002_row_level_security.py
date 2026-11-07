"""row level security

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07

Database-level tenant isolation. Each request/transaction sets two settings:
  app.user_id  - the authenticated user
  app.org_id   - the organization the request acts within (verified by the API first)
Policies compare rows against these. Unset or empty settings match nothing.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables where every row belongs to exactly one organization and one policy fits all commands.
TENANT_TABLES = (
    "agents",
    "agent_versions",
    "agent_tools",
    "integrations",
    "credentials",
    "agent_runs",
    "run_steps",
    "approvals",
    "conversations",
    "messages",
    "usage_records",
)
# Tables with bespoke policies.
SPECIAL_TABLES = ("organization_members", "organizations", "users", "audit_logs")

ORG = "app_current_org_id()"
USER = "app_current_user_id()"


def _enable(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    # FORCE applies policies to the table owner too (where the owner is not a superuser).
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _policy(table: str, name: str, command: str, using: str | None, check: str | None) -> None:
    clauses = f"FOR {command}"
    if using:
        clauses += f" USING ({using})"
    if check:
        clauses += f" WITH CHECK ({check})"
    op.execute(f"CREATE POLICY {name} ON {table} {clauses}")


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app_current_org_id() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.org_id', true), '')::uuid $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_current_user_id() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$
        """
    )

    for table in (*TENANT_TABLES, *SPECIAL_TABLES):
        _enable(table)

    for table in TENANT_TABLES:
        _policy(table, "tenant_isolation", "ALL", f"org_id = {ORG}", f"org_id = {ORG}")

    # organization_members: a user can see their own memberships (to list their organizations)
    # and every membership of the current organization. Writes only within the current org.
    _policy(
        "organization_members",
        "members_select",
        "SELECT",
        f"org_id = {ORG} OR user_id = {USER}",
        None,
    )
    _policy("organization_members", "members_insert", "INSERT", None, f"org_id = {ORG}")
    _policy(
        "organization_members", "members_update", "UPDATE", f"org_id = {ORG}", f"org_id = {ORG}"
    )
    _policy("organization_members", "members_delete", "DELETE", f"org_id = {ORG}", None)

    # organizations: visible if current or one the user belongs to. A new organization may only
    # be created by the user it names as creator.
    _policy(
        "organizations",
        "orgs_select",
        "SELECT",
        f"id = {ORG} OR id IN (SELECT org_id FROM organization_members WHERE user_id = {USER})",
        None,
    )
    _policy("organizations", "orgs_insert", "INSERT", None, f"created_by_id = {USER}")
    _policy("organizations", "orgs_update", "UPDATE", f"id = {ORG}", f"id = {ORG}")
    _policy("organizations", "orgs_delete", "DELETE", f"id = {ORG}", None)

    # users: yourself, plus the people in your current organization. No DELETE policy exists.
    _policy(
        "users",
        "users_select",
        "SELECT",
        f"id = {USER} OR id IN (SELECT user_id FROM organization_members WHERE org_id = {ORG})",
        None,
    )
    _policy("users", "users_insert", "INSERT", None, f"id = {USER}")
    _policy("users", "users_update", "UPDATE", f"id = {USER}", f"id = {USER}")

    # audit_logs: append-only (UPDATE/DELETE already revoked). Readable within the current org.
    _policy("audit_logs", "audit_select", "SELECT", f"org_id = {ORG}", None)
    _policy("audit_logs", "audit_insert", "INSERT", None, f"org_id IS NULL OR org_id = {ORG}")

    # Row policies cannot protect individual columns, so column privileges stop a user from
    # granting themselves is_super_admin.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_app') THEN
                REVOKE INSERT, UPDATE, DELETE ON users FROM agent_app;
                GRANT INSERT (id, email, full_name, avatar_url) ON users TO agent_app;
                GRANT UPDATE (email, full_name, avatar_url, updated_at) ON users TO agent_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_app') THEN
                GRANT INSERT, UPDATE, DELETE ON users TO agent_app;
            END IF;
        END
        $$;
        """
    )
    for table in (*TENANT_TABLES, *SPECIAL_TABLES):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    policies = {
        "organization_members": (
            "members_select",
            "members_insert",
            "members_update",
            "members_delete",
        ),
        "organizations": ("orgs_select", "orgs_insert", "orgs_update", "orgs_delete"),
        "users": ("users_select", "users_insert", "users_update"),
        "audit_logs": ("audit_select", "audit_insert"),
    }
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
    for table, names in policies.items():
        for name in names:
            op.execute(f"DROP POLICY {name} ON {table}")
    op.execute("DROP FUNCTION app_current_user_id()")
    op.execute("DROP FUNCTION app_current_org_id()")
