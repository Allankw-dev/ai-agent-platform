"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-07 08:58:40.347715
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _grant_runtime_privileges() -> None:
    """Give the non-superuser runtime role (agent_app) access, if that role exists.

    - Normal tables: SELECT/INSERT/UPDATE/DELETE.
    - audit_logs is append-only: no UPDATE or DELETE.
    - tools is a global catalog managed by migrations: read-only at runtime.
    - alembic_version is off limits.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agent_app;
                REVOKE UPDATE, DELETE ON audit_logs FROM agent_app;
                REVOKE INSERT, UPDATE, DELETE ON tools FROM agent_app;
                REVOKE ALL ON alembic_version FROM agent_app;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    op.create_table(
        "tools",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                "github",
                "gmail",
                "slack",
                "google_calendar",
                "http",
                "webhook",
                name="provider",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("is_sensitive", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("timeout_seconds > 0", name=op.f("ck_tools_timeout_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tools")),
        sa.UniqueConstraint("key", name=op.f("uq_tools_key")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("is_super_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9-]*$'", name=op.f("ck_organizations_slug_format")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_organizations_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "agents",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "active",
                "disabled",
                "archived",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_agents_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_version_id"],
            ["agent_versions.id"],
            name="fk_agents_current_version_id_agent_versions",
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_agents_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("id", "org_id", name="uq_agents_id_org_id"),
    )
    op.create_index(op.f("ix_agents_org_id"), "agents", ["org_id"], unique=False)
    op.create_index(
        "uq_agents_org_id_name_active",
        "agents",
        ["org_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "details",
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
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_audit_logs_org_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_org_id"), "audit_logs", ["org_id"], unique=False)
    op.create_index(
        "ix_audit_logs_org_id_created_at", "audit_logs", ["org_id", "created_at"], unique=False
    )
    op.create_table(
        "integrations",
        sa.Column(
            "provider",
            sa.Enum(
                "github",
                "gmail",
                "slack",
                "google_calendar",
                "http",
                "webhook",
                name="provider",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "disabled",
                "error",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_integrations_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_integrations_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint("id", "org_id", name="uq_integrations_id_org_id"),
        sa.UniqueConstraint(
            "org_id", "provider", "name", name="uq_integrations_org_id_provider_name"
        ),
    )
    op.create_index(op.f("ix_integrations_org_id"), "integrations", ["org_id"], unique=False)
    op.create_table(
        "organization_members",
        sa.Column("user_id", sa.Uuid(), nullable=False),
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
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_organization_members_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.UniqueConstraint("org_id", "user_id", name="uq_organization_members_org_id_user_id"),
    )
    op.create_index(
        op.f("ix_organization_members_org_id"), "organization_members", ["org_id"], unique=False
    )
    op.create_index(
        op.f("ix_organization_members_user_id"), "organization_members", ["user_id"], unique=False
    )
    op.create_table(
        "agent_versions",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_instructions", sa.Text(), nullable=False),
        sa.Column("objectives", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column(
            "model_params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "memory_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("version > 0", name=op.f("ck_agent_versions_version_positive")),
        sa.ForeignKeyConstraint(
            ["agent_id", "org_id"],
            ["agents.id", "agents.org_id"],
            name=op.f("fk_agent_versions_agent_id_agents"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_agent_versions_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_agent_versions_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_versions")),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_id_version"),
        sa.UniqueConstraint("id", "org_id", name="uq_agent_versions_id_org_id"),
    )
    op.create_index(
        op.f("ix_agent_versions_agent_id"), "agent_versions", ["agent_id"], unique=False
    )
    op.create_index(op.f("ix_agent_versions_org_id"), "agent_versions", ["org_id"], unique=False)
    op.create_table(
        "conversations",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id", "org_id"],
            ["agents.id", "agents.org_id"],
            name=op.f("fk_conversations_agent_id_agents"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_conversations_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_conversations_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("id", "org_id", name="uq_conversations_id_org_id"),
    )
    op.create_index(op.f("ix_conversations_agent_id"), "conversations", ["agent_id"], unique=False)
    op.create_index(op.f("ix_conversations_org_id"), "conversations", ["org_id"], unique=False)
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False)
    op.create_table(
        "credentials",
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "api_key",
                "oauth_token",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id", "org_id"],
            ["integrations.id", "integrations.org_id"],
            name=op.f("fk_credentials_integration_id_integrations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_credentials_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credentials")),
    )
    op.create_index(
        op.f("ix_credentials_integration_id"), "credentials", ["integration_id"], unique=False
    )
    op.create_index(op.f("ix_credentials_org_id"), "credentials", ["org_id"], unique=False)
    op.create_table(
        "agent_runs",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "awaiting_approval",
                "succeeded",
                "failed",
                "cancelled",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "trigger",
            sa.Enum(
                "manual",
                "test",
                "api",
                name="trigger",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("thread_id", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=12, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_agent_runs_tokens_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "org_id"],
            ["agents.id", "agents.org_id"],
            name=op.f("fk_agent_runs_agent_id_agents"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "org_id"],
            ["agent_versions.id", "agent_versions.org_id"],
            name=op.f("fk_agent_runs_agent_version_id_agent_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_agent_runs_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_agent_runs_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint("id", "org_id", name="uq_agent_runs_id_org_id"),
        sa.UniqueConstraint(
            "org_id", "idempotency_key", name="uq_agent_runs_org_id_idempotency_key"
        ),
    )
    op.create_index(op.f("ix_agent_runs_agent_id"), "agent_runs", ["agent_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_org_id"), "agent_runs", ["org_id"], unique=False)
    op.create_index(
        "ix_agent_runs_org_id_created_at", "agent_runs", ["org_id", "created_at"], unique=False
    )
    op.create_index("ix_agent_runs_org_id_status", "agent_runs", ["org_id", "status"], unique=False)
    op.create_table(
        "agent_tools",
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Uuid(), nullable=False),
        sa.Column(
            "requires_approval", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "org_id"],
            ["agent_versions.id", "agent_versions.org_id"],
            name=op.f("fk_agent_tools_agent_version_id_agent_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_agent_tools_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"], ["tools.id"], name=op.f("fk_agent_tools_tool_id_tools")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_tools")),
        sa.UniqueConstraint(
            "agent_version_id", "tool_id", name="uq_agent_tools_agent_version_id_tool_id"
        ),
    )
    op.create_index(
        op.f("ix_agent_tools_agent_version_id"), "agent_tools", ["agent_version_id"], unique=False
    )
    op.create_index(op.f("ix_agent_tools_org_id"), "agent_tools", ["org_id"], unique=False)
    op.create_index(op.f("ix_agent_tools_tool_id"), "agent_tools", ["tool_id"], unique=False)
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                "tool",
                "system",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id", "org_id"],
            ["conversations.id", "conversations.org_id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_messages_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "org_id"],
            ["agent_runs.id", "agent_runs.org_id"],
            name=op.f("fk_messages_run_id_agent_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(
        op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False
    )
    op.create_index(op.f("ix_messages_org_id"), "messages", ["org_id"], unique=False)
    op.create_table(
        "run_steps",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "step_type",
            sa.Enum(
                "llm_call",
                "tool_call",
                "approval",
                "error",
                name="step_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "succeeded",
                "failed",
                "skipped",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="running",
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("tool_key", sa.String(length=100), nullable=True),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_run_steps_sequence_non_negative")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_run_steps_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "org_id"],
            ["agent_runs.id", "agent_runs.org_id"],
            name=op.f("fk_run_steps_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_steps")),
        sa.UniqueConstraint("id", "org_id", name="uq_run_steps_id_org_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_steps_run_id_sequence"),
    )
    op.create_index(op.f("ix_run_steps_org_id"), "run_steps", ["org_id"], unique=False)
    op.create_index(op.f("ix_run_steps_run_id"), "run_steps", ["run_id"], unique=False)
    op.create_table(
        "usage_records",
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=12, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_usage_records_tokens_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "org_id"],
            ["agents.id", "agents.org_id"],
            name=op.f("fk_usage_records_agent_id_agents"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_usage_records_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "org_id"],
            ["agent_runs.id", "agent_runs.org_id"],
            name=op.f("fk_usage_records_run_id_agent_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
    )
    op.create_index(op.f("ix_usage_records_org_id"), "usage_records", ["org_id"], unique=False)
    op.create_index(
        "ix_usage_records_org_id_occurred_at",
        "usage_records",
        ["org_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "approvals",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("run_step_id", sa.Uuid(), nullable=True),
        sa.Column("tool_key", sa.String(length=100), nullable=False),
        sa.Column("proposed_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "expired",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_approvals_decided_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_approvals_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "org_id"],
            ["agent_runs.id", "agent_runs.org_id"],
            name=op.f("fk_approvals_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_step_id", "org_id"],
            ["run_steps.id", "run_steps.org_id"],
            name=op.f("fk_approvals_run_step_id_run_steps"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    op.create_index(op.f("ix_approvals_org_id"), "approvals", ["org_id"], unique=False)
    op.create_index("ix_approvals_org_id_status", "approvals", ["org_id", "status"], unique=False)
    op.create_index(op.f("ix_approvals_run_id"), "approvals", ["run_id"], unique=False)
    # agents <-> agent_versions reference each other, so this FK is added after both exist.
    op.create_foreign_key(
        "fk_agents_current_version_id_agent_versions",
        "agents",
        "agent_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _grant_runtime_privileges()


def downgrade() -> None:
    op.drop_constraint("fk_agents_current_version_id_agent_versions", "agents", type_="foreignkey")
    op.drop_index(op.f("ix_approvals_run_id"), table_name="approvals")
    op.drop_index("ix_approvals_org_id_status", table_name="approvals")
    op.drop_index(op.f("ix_approvals_org_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_usage_records_org_id_occurred_at", table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_org_id"), table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index(op.f("ix_run_steps_run_id"), table_name="run_steps")
    op.drop_index(op.f("ix_run_steps_org_id"), table_name="run_steps")
    op.drop_table("run_steps")
    op.drop_index(op.f("ix_messages_org_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_agent_tools_tool_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_org_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_agent_version_id"), table_name="agent_tools")
    op.drop_table("agent_tools")
    op.drop_index("ix_agent_runs_org_id_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_org_id_created_at", table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_org_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_agent_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index(op.f("ix_credentials_org_id"), table_name="credentials")
    op.drop_index(op.f("ix_credentials_integration_id"), table_name="credentials")
    op.drop_table("credentials")
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_org_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_agent_id"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(op.f("ix_agent_versions_org_id"), table_name="agent_versions")
    op.drop_index(op.f("ix_agent_versions_agent_id"), table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_index(op.f("ix_organization_members_user_id"), table_name="organization_members")
    op.drop_index(op.f("ix_organization_members_org_id"), table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_index(op.f("ix_integrations_org_id"), table_name="integrations")
    op.drop_table("integrations")
    op.drop_index("ix_audit_logs_org_id_created_at", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_org_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(
        "uq_agents_org_id_name_active",
        table_name="agents",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(op.f("ix_agents_org_id"), table_name="agents")
    op.drop_table("agents")
    op.drop_table("organizations")
    op.drop_table("users")
    op.drop_table("tools")
