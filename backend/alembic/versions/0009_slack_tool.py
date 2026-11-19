"""slack.send_message tool

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-19

Phase 4C. Adds the Slack tool to the global catalog. It needs a Slack integration (the tool's
provider), which holds the bot token and the channels that may be posted to. Posting changes
something outside the platform, so the tool is sensitive and always needs a person's approval.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SLACK_TOOL = {
    "key": "slack.send_message",
    "name": "Send Slack message",
    "description": (
        "Posts a message to a Slack channel that the connected integration allows. This sends a "
        "real message to real people, so a person must approve every message. Mentions of the "
        "whole channel (@channel, @here, @everyone) are disabled, and link previews are off."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "maxLength": 30,
                "description": (
                    "The Slack channel id, such as C0123456789 (not the channel's name). It must "
                    "be a channel the integration allows."
                ),
            },
            "text": {
                "type": "string",
                "minLength": 1,
                "maxLength": 3000,
                "description": "The message text, up to 3,000 characters.",
            },
        },
        "required": ["channel", "text"],
        "additionalProperties": False,
    },
    "provider": "slack",
    "is_sensitive": True,
    "timeout_seconds": 15,
}


def upgrade() -> None:
    tools = sa.table(
        "tools",
        sa.column("key", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("input_schema", sa.JSON),
        sa.column("provider", sa.String),
        sa.column("is_sensitive", sa.Boolean),
        sa.column("timeout_seconds", sa.Integer),
    )
    op.bulk_insert(tools, [SLACK_TOOL])


def downgrade() -> None:
    key = "'slack.send_message'"
    # Grants of this tool go first: an agent version cannot keep a tool that no longer exists.
    op.execute(f"DELETE FROM agent_tools WHERE tool_id IN (SELECT id FROM tools WHERE key = {key})")
    op.execute(f"DELETE FROM tools WHERE key = {key}")
