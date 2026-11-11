"""Row Level Security, tested as the real restricted runtime role (agent_app).

Data is seeded as the owner (which bypasses RLS); every assertion runs as agent_app.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError

from tests.integration.seed import TENANT_TABLES, OrgData, seed_org, seed_tool


@dataclass
class World:
    owner: Engine
    runtime: Engine
    a: OrgData
    b: OrgData


@pytest.fixture
def world(engine: Engine, runtime_url: str) -> Iterator[World]:
    with engine.begin() as conn:
        tool = seed_tool(conn)
        a = seed_org(conn, "org-a", tool)
        b = seed_org(conn, "org-b", tool)
    runtime = create_engine(runtime_url)
    yield World(owner=engine, runtime=runtime, a=a, b=b)
    runtime.dispose()


@contextmanager
def acting_as(
    world: World,
    *,
    user: uuid.UUID | None = None,
    org: uuid.UUID | None = None,
    invite_hash: str | None = None,
) -> Iterator[Connection]:
    """A runtime-role transaction with the tenant context set, like one API request."""
    with world.runtime.begin() as conn:
        conn.execute(
            text(
                "SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true), "
                "set_config('app.invite_hash', :h, true)"
            ),
            {"u": str(user) if user else "", "o": str(org) if org else "", "h": invite_hash or ""},
        )
        yield conn


def _scalar(conn: Connection, sql: str, **params: object) -> int:
    return int(conn.execute(text(sql), params).scalar_one())


def _ids(conn: Connection, sql: str, **params: object) -> set[uuid.UUID]:
    return {uuid.UUID(str(row[0])) for row in conn.execute(text(sql), params)}


# ---------- reading ----------


def test_without_context_every_table_is_empty(world: World) -> None:
    with acting_as(world) as conn:
        for table in (*TENANT_TABLES, "organizations", "users"):
            assert _scalar(conn, f"SELECT count(*) FROM {table}") == 0, table


def test_org_context_sees_only_its_own_rows(world: World) -> None:
    with acting_as(world, org=world.a.org) as conn:
        for table in TENANT_TABLES:
            own = _scalar(conn, f"SELECT count(*) FROM {table} WHERE org_id = :o", o=world.a.org)
            others = _scalar(conn, f"SELECT count(*) FROM {table} WHERE org_id = :o", o=world.b.org)
            assert own == 1, table
            assert others == 0, table


def test_an_organizations_data_is_invisible_to_the_other_and_vice_versa(world: World) -> None:
    with acting_as(world, org=world.b.org) as conn:
        assert _ids(conn, "SELECT id FROM agents") == {world.b.agent}


def test_empty_context_value_is_treated_as_unset(world: World) -> None:
    with world.runtime.begin() as conn:
        conn.execute(text("SELECT set_config('app.org_id', '', true)"))
        assert _scalar(conn, "SELECT count(*) FROM agents") == 0


def test_user_context_lists_only_their_own_organizations(world: World) -> None:
    with acting_as(world, user=world.a.user) as conn:
        assert _ids(conn, "SELECT id FROM organizations") == {world.a.org}


def test_user_context_sees_only_their_own_memberships(world: World) -> None:
    with acting_as(world, user=world.a.user) as conn:
        assert _ids(conn, "SELECT user_id FROM organization_members") == {world.a.user}


def test_org_context_shows_member_profiles_but_not_strangers(world: World) -> None:
    with world.owner.begin() as conn:
        colleague = uuid.UUID(
            str(
                conn.execute(
                    text("INSERT INTO users (email) VALUES ('colleague@example.com') RETURNING id")
                ).scalar_one()
            )
        )
        conn.execute(
            text(
                "INSERT INTO organization_members (org_id, user_id, role) VALUES (:o, :u, 'member')"
            ),
            {"o": world.a.org, "u": colleague},
        )
    with acting_as(world, user=world.a.user, org=world.a.org) as conn:
        assert _ids(conn, "SELECT id FROM users") == {world.a.user, colleague}


def test_user_without_org_context_sees_only_themselves(world: World) -> None:
    with acting_as(world, user=world.a.user) as conn:
        assert _ids(conn, "SELECT id FROM users") == {world.a.user}


def test_tool_catalog_is_readable_without_context(world: World) -> None:
    with acting_as(world) as conn:
        assert _scalar(conn, "SELECT count(*) FROM tools") >= 1


# ---------- writing ----------


def test_cannot_insert_a_row_for_another_organization(world: World) -> None:
    with pytest.raises(ProgrammingError), acting_as(world, org=world.a.org) as conn:
        conn.execute(
            text("INSERT INTO agents (org_id, name) VALUES (:o, 'smuggled')"), {"o": world.b.org}
        )


def test_cannot_insert_without_any_context(world: World) -> None:
    with pytest.raises(ProgrammingError), acting_as(world) as conn:
        conn.execute(text("INSERT INTO agents (org_id, name) VALUES (:o, 'x')"), {"o": world.a.org})


def test_can_insert_into_the_current_organization(world: World) -> None:
    with acting_as(world, org=world.a.org) as conn:
        conn.execute(
            text("INSERT INTO agents (org_id, name) VALUES (:o, 'second')"), {"o": world.a.org}
        )
        assert _scalar(conn, "SELECT count(*) FROM agents") == 2


def test_cannot_update_or_delete_another_organizations_rows(world: World) -> None:
    with acting_as(world, org=world.a.org) as conn:
        updated = conn.execute(
            text("UPDATE agents SET name = 'hacked' WHERE id = :i"), {"i": world.b.agent}
        )
        assert updated.rowcount == 0
        for table in TENANT_TABLES:
            if table in ("audit_logs", "agent_versions", "agent_tools"):
                continue  # append-only / immutable, covered separately
            deleted = conn.execute(
                text(f"DELETE FROM {table} WHERE org_id = :o"), {"o": world.b.org}
            )
            assert deleted.rowcount == 0, table
    with world.owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT name FROM agents WHERE id = :i"), {"i": world.b.agent}
            ).scalar_one()
            == "bot"
        )
        assert (
            _scalar(conn, "SELECT count(*) FROM agent_runs WHERE org_id = :o", o=world.b.org) == 1
        )


def test_cannot_move_a_row_into_another_organization(world: World) -> None:
    with pytest.raises(ProgrammingError), acting_as(world, org=world.a.org) as conn:
        conn.execute(
            text("UPDATE agents SET org_id = :b WHERE id = :i"),
            {"b": world.b.org, "i": world.a.agent},
        )


def test_cannot_add_a_member_to_another_organization(world: World) -> None:
    with (
        pytest.raises(ProgrammingError),
        acting_as(world, user=world.a.user, org=world.a.org) as conn,
    ):
        conn.execute(
            text(
                "INSERT INTO organization_members (org_id, user_id, role) VALUES (:o, :u, 'owner')"
            ),
            {"o": world.b.org, "u": world.a.user},
        )


# ---------- creating an organization ----------


def test_user_can_create_an_organization_and_become_its_owner(world: World) -> None:
    new_org = uuid.uuid4()
    with acting_as(world, user=world.a.user, org=new_org) as conn:
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, slug, created_by_id) VALUES (:i, 'New', 'new', :u)"
            ),
            {"i": new_org, "u": world.a.user},
        )
        conn.execute(
            text(
                "INSERT INTO organization_members (org_id, user_id, role) VALUES (:o, :u, 'owner')"
            ),
            {"o": new_org, "u": world.a.user},
        )
    with acting_as(world, user=world.a.user) as conn:
        assert _ids(conn, "SELECT id FROM organizations") == {world.a.org, new_org}


def test_cannot_create_an_organization_in_someone_elses_name(world: World) -> None:
    new_org = uuid.uuid4()
    with pytest.raises(ProgrammingError), acting_as(world, user=world.a.user, org=new_org) as conn:
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, slug, created_by_id) VALUES (:i, 'X', 'x', :u)"
            ),
            {"i": new_org, "u": world.b.user},
        )


# ---------- users table ----------


def test_user_can_update_their_own_name(world: World) -> None:
    with acting_as(world, user=world.a.user) as conn:
        updated = conn.execute(
            text("UPDATE users SET full_name = 'Ada' WHERE id = :u"), {"u": world.a.user}
        )
        assert updated.rowcount == 1


def test_user_cannot_edit_another_user(world: World) -> None:
    with acting_as(world, user=world.a.user) as conn:
        updated = conn.execute(
            text("UPDATE users SET full_name = 'pwned' WHERE id = :u"), {"u": world.b.user}
        )
        assert updated.rowcount == 0


def test_user_cannot_make_themselves_super_admin(world: World) -> None:
    with pytest.raises(ProgrammingError), acting_as(world, user=world.a.user) as conn:
        conn.execute(
            text("UPDATE users SET is_super_admin = true WHERE id = :u"), {"u": world.a.user}
        )


def test_new_user_cannot_be_created_as_super_admin(world: World) -> None:
    new_user = uuid.uuid4()
    with pytest.raises(ProgrammingError), acting_as(world, user=new_user) as conn:
        conn.execute(
            text("INSERT INTO users (id, email, is_super_admin) VALUES (:i, 'x@x.com', true)"),
            {"i": new_user},
        )


def test_users_cannot_be_deleted_by_the_runtime_role(world: World) -> None:
    with pytest.raises(ProgrammingError), acting_as(world, user=world.a.user) as conn:
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": world.a.user})


# ---------- audit log ----------


def test_audit_log_is_scoped_and_append_only(world: World) -> None:
    with acting_as(world, org=world.a.org) as conn:
        conn.execute(
            text("INSERT INTO audit_logs (org_id, action, resource_type) VALUES (:o, 'x', 'y')"),
            {"o": world.a.org},
        )
        conn.execute(text("INSERT INTO audit_logs (action, resource_type) VALUES ('system', 'y')"))
        assert _scalar(conn, "SELECT count(*) FROM audit_logs") == 2  # seeded + new, not b's
    with pytest.raises(ProgrammingError), acting_as(world, org=world.a.org) as conn:
        conn.execute(
            text("INSERT INTO audit_logs (org_id, action, resource_type) VALUES (:o, 'x', 'y')"),
            {"o": world.b.org},
        )


# ---------- transaction scoping ----------


def test_context_does_not_leak_into_the_next_transaction(world: World) -> None:
    """Pooled connections are reused; a finished request must leave no context behind."""
    with world.runtime.connect() as conn:
        with conn.begin():
            conn.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(world.a.org)})
            assert _scalar(conn, "SELECT count(*) FROM agents") == 1
        with conn.begin():
            assert _scalar(conn, "SELECT count(*) FROM agents") == 0


# ---------- invitations ----------


def test_invite_token_reveals_exactly_one_invitation(world: World) -> None:
    """Holding a token lets you see that invitation, even from outside the organization."""
    with acting_as(world, invite_hash=world.a.invite_hash) as conn:
        assert _scalar(conn, "SELECT count(*) FROM organization_invitations") == 1
        assert (
            _scalar(
                conn,
                "SELECT count(*) FROM organization_invitations WHERE org_id = :o",
                o=world.b.org,
            )
            == 0
        )


def test_wrong_token_reveals_nothing(world: World) -> None:
    with acting_as(world, invite_hash="0" * 64) as conn:
        assert _scalar(conn, "SELECT count(*) FROM organization_invitations") == 0


def test_invite_token_does_not_unlock_other_tables(world: World) -> None:
    with acting_as(world, invite_hash=world.a.invite_hash) as conn:
        for table in ("agents", "organization_members", "agent_runs", "credentials"):
            assert _scalar(conn, f"SELECT count(*) FROM {table}") == 0, table


def test_invite_token_does_not_allow_writing_to_the_organization(world: World) -> None:
    with pytest.raises(ProgrammingError), acting_as(world, invite_hash=world.a.invite_hash) as conn:
        conn.execute(
            text(
                "INSERT INTO organization_members (org_id, user_id, role) VALUES (:o, :u, 'member')"
            ),
            {"o": world.a.org, "u": world.b.user},
        )


def test_audit_entries_outlive_their_organization(world: World) -> None:
    """Deleting an organization must not detach its history from it."""
    with world.owner.begin() as conn:
        conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": world.a.org})
        kept = _scalar(conn, "SELECT count(*) FROM audit_logs WHERE org_id = :o", o=world.a.org)
    assert kept == 1
    # Nobody acting within another organization can read them.
    with acting_as(world, org=world.b.org) as conn:
        assert (
            _scalar(conn, "SELECT count(*) FROM audit_logs WHERE org_id = :o", o=world.a.org) == 0
        )


def test_agent_versions_are_immutable_for_the_runtime_role(world: World) -> None:
    """A version is a snapshot: it can be added and read, never edited or removed."""
    for sql in (
        "UPDATE agent_versions SET model = 'tampered'",
        "DELETE FROM agent_versions",
        "UPDATE agent_tools SET requires_approval = false",
        "DELETE FROM agent_tools",
    ):
        with pytest.raises(ProgrammingError), acting_as(world, org=world.a.org) as conn:
            conn.execute(text(sql))
    with acting_as(world, org=world.a.org) as conn:
        assert _scalar(conn, "SELECT count(*) FROM agent_versions") == 1
        conn.execute(
            text(
                "INSERT INTO agent_versions (org_id, agent_id, version, system_instructions, model) "
                "VALUES (:o, :a, 2, 'new', 'm')"
            ),
            {"o": world.a.org, "a": world.a.agent},
        )
