import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from tests.integration.conftest import runtime_role_exists


def _insert_id(conn: Connection, sql: str, params: dict[str, object]) -> uuid.UUID:
    return uuid.UUID(str(conn.execute(text(sql), params).scalar_one()))


def _org(conn: Connection, slug: str) -> uuid.UUID:
    return _insert_id(
        conn,
        "INSERT INTO organizations (name, slug) VALUES (:n, :s) RETURNING id",
        {"n": slug, "s": slug},
    )


def _user(conn: Connection, email: str) -> uuid.UUID:
    return _insert_id(conn, "INSERT INTO users (email) VALUES (:e) RETURNING id", {"e": email})


def _agent(conn: Connection, org_id: uuid.UUID, name: str = "bot") -> uuid.UUID:
    return _insert_id(
        conn,
        "INSERT INTO agents (org_id, name) VALUES (:o, :n) RETURNING id",
        {"o": org_id, "n": name},
    )


def _version(conn: Connection, org_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    return _insert_id(
        conn,
        "INSERT INTO agent_versions (org_id, agent_id, version, system_instructions, model) "
        "VALUES (:o, :a, 1, 'be helpful', 'claude-sonnet-4-6') RETURNING id",
        {"o": org_id, "a": agent_id},
    )


def test_user_can_join_an_org_only_once(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        org, user = _org(conn, "acme"), _user(conn, "a@example.com")
        for _ in range(2):
            conn.execute(
                text(
                    "INSERT INTO organization_members (org_id, user_id, role) "
                    "VALUES (:o, :u, 'member')"
                ),
                {"o": org, "u": user},
            )


def test_invalid_role_is_rejected(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        org, user = _org(conn, "acme"), _user(conn, "a@example.com")
        conn.execute(
            text(
                "INSERT INTO organization_members (org_id, user_id, role) "
                "VALUES (:o, :u, 'superhero')"
            ),
            {"o": org, "u": user},
        )


def test_invalid_org_slug_is_rejected(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _org(conn, "Not Valid!")


def test_agent_names_unique_among_active_agents(engine: Engine) -> None:
    with engine.begin() as conn:
        org = _org(conn, "acme")
        first = _agent(conn, org, "support-bot")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _agent(conn, org, "support-bot")
    # After soft-deleting the first agent, the name can be reused.
    with engine.begin() as conn:
        conn.execute(text("UPDATE agents SET deleted_at = now() WHERE id = :i"), {"i": first})
        _agent(conn, org, "support-bot")


def test_run_cannot_reference_another_orgs_agent(engine: Engine) -> None:
    """The key multi-tenancy guarantee: cross-organization references are impossible."""
    with engine.begin() as conn:
        org_a, org_b = _org(conn, "org-a"), _org(conn, "org-b")
        agent_a = _agent(conn, org_a)
        version_a = _version(conn, org_a, agent_a)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_runs (org_id, agent_id, agent_version_id, trigger) "
                "VALUES (:o, :a, :v, 'manual')"
            ),
            {"o": org_b, "a": agent_a, "v": version_a},
        )


def test_run_in_same_org_is_accepted(engine: Engine) -> None:
    with engine.begin() as conn:
        org = _org(conn, "acme")
        agent = _agent(conn, org)
        version = _version(conn, org, agent)
        conn.execute(
            text(
                "INSERT INTO agent_runs (org_id, agent_id, agent_version_id, trigger) "
                "VALUES (:o, :a, :v, 'manual')"
            ),
            {"o": org, "a": agent, "v": version},
        )


def test_idempotency_key_unique_per_org(engine: Engine) -> None:
    with engine.begin() as conn:
        org = _org(conn, "acme")
        agent = _agent(conn, org)
        version = _version(conn, org, agent)
    insert = text(
        "INSERT INTO agent_runs (org_id, agent_id, agent_version_id, trigger, idempotency_key) "
        "VALUES (:o, :a, :v, 'api', 'key-1')"
    )
    params = {"o": org, "a": agent, "v": version}
    with engine.begin() as conn:
        conn.execute(insert, params)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert, params)


def test_runtime_role_cannot_modify_audit_log(engine: Engine) -> None:
    if not runtime_role_exists(engine):
        pytest.skip("runtime role agent_app not present (created by docker/postgres-init.sql)")
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE agent_app"))
        conn.execute(text("INSERT INTO audit_logs (action, resource_type) VALUES ('x', 'y')"))
    with pytest.raises(ProgrammingError), engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE agent_app"))
        conn.execute(text("UPDATE audit_logs SET action = 'tampered'"))
    with pytest.raises(ProgrammingError), engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE agent_app"))
        conn.execute(text("DELETE FROM audit_logs"))


def test_runtime_role_cannot_modify_tool_catalog(engine: Engine) -> None:
    if not runtime_role_exists(engine):
        pytest.skip("runtime role agent_app not present (created by docker/postgres-init.sql)")
    with pytest.raises(ProgrammingError), engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE agent_app"))
        conn.execute(
            text(
                "INSERT INTO tools (key, name, description, input_schema) "
                "VALUES ('evil', 'Evil', 'x', '{}')"
            )
        )
