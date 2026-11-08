"""Seed one row in every tenant table for an organization (as the owner role)."""

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

# Every table that carries an org_id column.
TENANT_TABLES = (
    "organization_members",
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
    "audit_logs",
    "organization_invitations",
)


@dataclass(frozen=True)
class OrgData:
    org: uuid.UUID
    user: uuid.UUID
    agent: uuid.UUID
    invite_hash: str


def _one(conn: Connection, sql: str, **params: object) -> uuid.UUID:
    return uuid.UUID(str(conn.execute(text(sql), params).scalar_one()))


def seed_tool(conn: Connection) -> uuid.UUID:
    return _one(
        conn,
        "INSERT INTO tools (key, name, description, input_schema) "
        "VALUES ('http.request', 'HTTP', 'Call an API', CAST('{}' AS jsonb)) RETURNING id",
    )


def seed_org(conn: Connection, slug: str, tool: uuid.UUID) -> OrgData:
    user = _one(conn, "INSERT INTO users (email) VALUES (:e) RETURNING id", e=f"{slug}@example.com")
    org = _one(
        conn,
        "INSERT INTO organizations (name, slug, created_by_id) VALUES (:s, :s, :u) RETURNING id",
        s=slug,
        u=user,
    )
    conn.execute(
        text("INSERT INTO organization_members (org_id, user_id, role) VALUES (:o, :u, 'owner')"),
        {"o": org, "u": user},
    )
    agent = _one(conn, "INSERT INTO agents (org_id, name) VALUES (:o, 'bot') RETURNING id", o=org)
    version = _one(
        conn,
        "INSERT INTO agent_versions (org_id, agent_id, version, system_instructions, model) "
        "VALUES (:o, :a, 1, 'help', 'claude-sonnet-4-6') RETURNING id",
        o=org,
        a=agent,
    )
    conn.execute(
        text("INSERT INTO agent_tools (org_id, agent_version_id, tool_id) VALUES (:o, :v, :t)"),
        {"o": org, "v": version, "t": tool},
    )
    integration = _one(
        conn,
        "INSERT INTO integrations (org_id, provider, name) VALUES (:o, 'slack', 'ws') RETURNING id",
        o=org,
    )
    conn.execute(
        text(
            "INSERT INTO credentials (org_id, integration_id, kind, encrypted_payload) "
            "VALUES (:o, :i, 'api_key', decode('00', 'hex'))"
        ),
        {"o": org, "i": integration},
    )
    conversation = _one(
        conn,
        "INSERT INTO conversations (org_id, agent_id) VALUES (:o, :a) RETURNING id",
        o=org,
        a=agent,
    )
    run = _one(
        conn,
        "INSERT INTO agent_runs (org_id, agent_id, agent_version_id, trigger) "
        "VALUES (:o, :a, :v, 'manual') RETURNING id",
        o=org,
        a=agent,
        v=version,
    )
    conn.execute(
        text(
            "INSERT INTO run_steps (org_id, run_id, sequence, step_type) "
            "VALUES (:o, :r, 0, 'llm_call')"
        ),
        {"o": org, "r": run},
    )
    conn.execute(
        text(
            "INSERT INTO approvals (org_id, run_id, tool_key, proposed_input) "
            "VALUES (:o, :r, 'http.request', CAST('{}' AS jsonb))"
        ),
        {"o": org, "r": run},
    )
    conn.execute(
        text(
            "INSERT INTO messages (org_id, conversation_id, role, content) "
            "VALUES (:o, :c, 'user', CAST('{}' AS jsonb))"
        ),
        {"o": org, "c": conversation},
    )
    conn.execute(
        text("INSERT INTO usage_records (org_id, model) VALUES (:o, 'claude-sonnet-4-6')"),
        {"o": org},
    )
    conn.execute(
        text("INSERT INTO audit_logs (org_id, action, resource_type) VALUES (:o, 'seed', 'org')"),
        {"o": org},
    )
    invite_hash = hashlib.sha256(f"token-{slug}".encode()).hexdigest()
    conn.execute(
        text(
            "INSERT INTO organization_invitations (org_id, email, role, token_hash, expires_at) "
            "VALUES (:o, :e, 'member', :h, now() + interval '7 days')"
        ),
        {"o": org, "e": f"invitee-{slug}@example.com", "h": invite_hash},
    )
    return OrgData(org=org, user=user, agent=agent, invite_hash=invite_hash)
