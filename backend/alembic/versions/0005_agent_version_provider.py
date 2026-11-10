"""agent version provider, built-in tool catalog, immutable versions

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09

- agent_versions.provider: which LLM provider a version uses (gemini today, anthropic later).
- Seeds the two harmless built-in tools used to exercise the agent loop. Real integrations are
  added by later migrations. The runtime role can only read this catalog.
- Agent versions (and their tool assignments) are immutable snapshots: the runtime role may insert
  and read them but never update or delete them. Changing an agent creates a new version.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUILTIN_TOOLS = [
    {
        "key": "utility.current_time",
        "name": "Current time",
        "description": "Returns the current date and time in a given IANA timezone (default UTC).",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name such as Africa/Nairobi. Defaults to UTC.",
                }
            },
            "additionalProperties": False,
        },
        "is_sensitive": False,
        "timeout_seconds": 5,
    },
    {
        "key": "utility.calculate",
        "name": "Calculator",
        "description": "Evaluates an arithmetic expression using + - * / ** % and parentheses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression, for example (2 + 3) * 4.",
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
        "is_sensitive": False,
        "timeout_seconds": 5,
    },
]


def upgrade() -> None:
    op.add_column(
        "agent_versions",
        sa.Column(
            "provider",
            sa.String(length=32),
            server_default="gemini",
            nullable=False,
        ),
    )
    # Alembic does not create the CHECK for a column added this way, so add it explicitly.
    op.create_check_constraint(
        op.f("ck_agent_versions_provider"),
        "agent_versions",
        "provider IN ('gemini', 'anthropic')",
    )

    tools = sa.table(
        "tools",
        sa.column("key", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("input_schema", sa.JSON),
        sa.column("is_sensitive", sa.Boolean),
        sa.column("timeout_seconds", sa.Integer),
    )
    op.bulk_insert(tools, BUILTIN_TOOLS)

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_app') THEN
                REVOKE UPDATE, DELETE ON agent_versions FROM agent_app;
                REVOKE UPDATE, DELETE ON agent_tools FROM agent_app;
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
                GRANT UPDATE, DELETE ON agent_versions TO agent_app;
                GRANT UPDATE, DELETE ON agent_tools TO agent_app;
            END IF;
        END
        $$;
        """
    )
    keys = json.dumps([tool["key"] for tool in BUILTIN_TOOLS])
    op.execute(
        f"DELETE FROM agent_tools WHERE tool_id IN "
        f"(SELECT id FROM tools WHERE key IN (SELECT jsonb_array_elements_text('{keys}'::jsonb)))"
    )
    op.execute(
        f"DELETE FROM tools WHERE key IN (SELECT jsonb_array_elements_text('{keys}'::jsonb))"
    )
    op.drop_constraint(op.f("ck_agent_versions_provider"), "agent_versions", type_="check")
    op.drop_column("agent_versions", "provider")
