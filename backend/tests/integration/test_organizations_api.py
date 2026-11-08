"""Organizations, members and roles through the real API, as the restricted database role."""

from dataclasses import dataclass
from typing import Any

import pytest

from tests.integration.api_helpers import Api

OWNER = "owner@acme.example.com"
ADMIN = "admin@acme.example.com"
DEV = "dev@acme.example.com"
MEMBER = "member@acme.example.com"
STRANGER = "stranger@other.example.com"


@dataclass
class Acme:
    api: Api
    org_id: str

    @property
    def base(self) -> str:
        return f"/api/v1/organizations/{self.org_id}"

    def uid(self, email: str) -> str:
        return str(self.api.user_id(email))


@pytest.fixture
async def acme(api: Api) -> Acme:
    org = await api.create_org(OWNER, "Acme Inc")
    await api.add_member(org["id"], ADMIN, "admin")
    await api.add_member(org["id"], DEV, "developer")
    await api.add_member(org["id"], MEMBER, "member")
    # The stranger belongs to a different organization entirely.
    await api.create_org(STRANGER, "Other Co")
    return Acme(api=api, org_id=org["id"])


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# ---------- creating and listing ----------


async def test_creating_an_organization_makes_you_its_owner(api: Api) -> None:
    response = await api.post(OWNER, "/api/v1/organizations", json={"name": "Acme Inc"})
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "owner"
    assert body["slug"] == "acme-inc"

    listing = (await api.get(OWNER, "/api/v1/organizations")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == body["id"]


async def test_custom_slug_and_conflicts(api: Api) -> None:
    await api.create_org(OWNER, "Acme", slug="acme")
    clash = await api.post(STRANGER, "/api/v1/organizations", json={"name": "X Co", "slug": "acme"})
    assert clash.status_code == 409
    assert _code(clash) == "slug_taken"

    invalid = await api.post(
        STRANGER, "/api/v1/organizations", json={"name": "X Co", "slug": "Bad Slug"}
    )
    assert invalid.status_code == 422
    assert _code(invalid) == "validation_error"


async def test_generated_slugs_never_collide(api: Api) -> None:
    first = await api.create_org(OWNER, "Acme")
    second = await api.create_org(STRANGER, "Acme")
    assert first["slug"] == "acme"
    assert second["slug"].startswith("acme-") and second["slug"] != first["slug"]


@pytest.mark.parametrize("name", ["", " ", "A", "   x   "])
async def test_organization_name_is_validated(api: Api, name: str) -> None:
    response = await api.post(OWNER, "/api/v1/organizations", json={"name": name})
    assert response.status_code == 422


async def test_listing_shows_only_my_organizations(api: Api) -> None:
    await api.create_org(OWNER, "One")
    await api.create_org(OWNER, "Two")
    await api.create_org(STRANGER, "Theirs")
    mine = (await api.get(OWNER, "/api/v1/organizations")).json()
    assert mine["total"] == 2
    assert {item["name"] for item in mine["items"]} == {"One", "Two"}
    page = (await api.get(OWNER, "/api/v1/organizations", params={"limit": 1})).json()
    assert len(page["items"]) == 1 and page["total"] == 2


# ---------- isolation ----------


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("PATCH", "", {"name": "Hacked"}),
        ("DELETE", "", None),
        ("GET", "/members", None),
        ("GET", "/invitations", None),
        ("POST", "/invitations", {"email": "x@y.example.com", "role": "member"}),
    ],
)
async def test_non_members_get_404_not_403(
    acme: Acme, method: str, suffix: str, body: dict[str, Any] | None
) -> None:
    response = await acme.api.request(STRANGER, method, acme.base + suffix, json=body)
    assert response.status_code == 404
    assert _code(response) == "organization_not_found"


async def test_unknown_organization_looks_the_same_as_a_forbidden_one(api: Api) -> None:
    response = await api.get(OWNER, "/api/v1/organizations/6f2b1c1e-0000-4000-8000-000000000000")
    assert response.status_code == 404
    assert _code(response) == "organization_not_found"


# ---------- updating and deleting ----------


@pytest.mark.parametrize(("who", "status"), [(OWNER, 200), (ADMIN, 200), (DEV, 403), (MEMBER, 403)])
async def test_who_can_rename_the_organization(acme: Acme, who: str, status: int) -> None:
    response = await acme.api.patch(who, acme.base, json={"name": "Renamed"})
    assert response.status_code == status
    if status == 403:
        assert _code(response) == "forbidden"
    else:
        assert response.json()["name"] == "Renamed"


@pytest.mark.parametrize(("who", "status"), [(ADMIN, 403), (DEV, 403), (MEMBER, 403)])
async def test_only_the_owner_can_delete(acme: Acme, who: str, status: int) -> None:
    response = await acme.api.delete(who, acme.base)
    assert response.status_code == status
    assert (await acme.api.get(OWNER, acme.base)).status_code == 200


async def test_deleting_removes_the_organization_and_everything_in_it(acme: Acme) -> None:
    acme.api.execute("INSERT INTO agents (org_id, name) VALUES (:o, 'bot')", o=acme.org_id)
    response = await acme.api.delete(OWNER, acme.base)
    assert response.status_code == 204
    assert (await acme.api.get(OWNER, acme.base)).status_code == 404
    for table in ("organization_members", "agents", "organization_invitations"):
        count = acme.api.scalar(f"SELECT count(*) FROM {table} WHERE org_id = :o", o=acme.org_id)
        assert count == 0, table
    # The audit trail survives the organization it describes.
    assert (
        acme.api.scalar("SELECT count(*) FROM audit_logs WHERE action = 'organization.deleted'")
        == 1
    )
    # The other organization is untouched.
    assert (await acme.api.get(STRANGER, "/api/v1/organizations")).json()["total"] == 1


# ---------- members ----------


async def test_any_member_can_list_members(acme: Acme) -> None:
    for who in (OWNER, ADMIN, DEV, MEMBER):
        response = await acme.api.get(who, acme.base + "/members")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4
        assert {m["email"] for m in body["items"]} == {OWNER, ADMIN, DEV, MEMBER}


async def test_member_list_is_paginated(acme: Acme) -> None:
    page = (await acme.api.get(OWNER, acme.base + "/members", params={"limit": 2})).json()
    assert len(page["items"]) == 2 and page["total"] == 4 and page["limit"] == 2
    rest = (
        await acme.api.get(OWNER, acme.base + "/members", params={"limit": 2, "offset": 2})
    ).json()
    assert len(rest["items"]) == 2
    assert {m["user_id"] for m in page["items"]}.isdisjoint({m["user_id"] for m in rest["items"]})
    bad = await acme.api.get(OWNER, acme.base + "/members", params={"limit": 0})
    assert bad.status_code == 422


async def _set_role(acme: Acme, actor: str, target: str, role: str) -> Any:
    return await acme.api.patch(
        actor, f"{acme.base}/members/{acme.uid(target)}", json={"role": role}
    )


async def test_owner_can_set_any_role(acme: Acme) -> None:
    assert (await _set_role(acme, OWNER, MEMBER, "developer")).status_code == 200
    assert (await _set_role(acme, OWNER, DEV, "admin")).status_code == 200
    members = (await acme.api.get(OWNER, acme.base + "/members")).json()["items"]
    roles = {m["email"]: m["role"] for m in members}
    assert roles[MEMBER] == "developer" and roles[DEV] == "admin"


async def test_admin_can_manage_below_admin_but_not_above(acme: Acme) -> None:
    assert (await _set_role(acme, ADMIN, MEMBER, "developer")).status_code == 200
    # An admin cannot create peers or superiors...
    for role in ("admin", "owner"):
        response = await _set_role(acme, ADMIN, MEMBER, role)
        assert response.status_code == 403 and _code(response) == "insufficient_role"
    # ...nor touch the owner.
    response = await _set_role(acme, ADMIN, OWNER, "member")
    assert response.status_code == 403 and _code(response) == "insufficient_role"


async def test_admin_cannot_touch_another_admin(acme: Acme) -> None:
    await acme.api.add_member(acme.org_id, "admin2@acme.example.com", "admin")
    response = await _set_role(acme, ADMIN, "admin2@acme.example.com", "member")
    assert response.status_code == 403


@pytest.mark.parametrize("actor", [DEV, MEMBER])
async def test_developers_and_members_cannot_change_roles(acme: Acme, actor: str) -> None:
    response = await _set_role(acme, actor, MEMBER if actor == DEV else DEV, "admin")
    assert response.status_code == 403 and _code(response) == "forbidden"


async def test_you_cannot_change_your_own_role(acme: Acme) -> None:
    for actor in (OWNER, ADMIN):
        response = await _set_role(acme, actor, actor, "member")
        assert response.status_code == 403 and _code(response) == "cannot_change_own_role"


async def test_changing_the_role_of_a_non_member_is_a_404(acme: Acme) -> None:
    response = await acme.api.patch(
        OWNER, f"{acme.base}/members/{acme.uid(STRANGER)}", json={"role": "member"}
    )
    assert response.status_code == 404 and _code(response) == "member_not_found"


async def test_invalid_role_is_rejected(acme: Acme) -> None:
    assert (await _set_role(acme, OWNER, MEMBER, "emperor")).status_code == 422


async def test_ownership_can_be_transferred_but_the_last_owner_is_protected(acme: Acme) -> None:
    assert (await _set_role(acme, OWNER, ADMIN, "owner")).status_code == 200
    assert (
        await _set_role(acme, ADMIN, OWNER, "member")
    ).status_code == 200  # new owner demotes old
    # ADMIN is now the only owner and cannot leave or be removed.
    leave = await acme.api.delete(ADMIN, f"{acme.base}/members/{acme.uid(ADMIN)}")
    assert leave.status_code == 409 and _code(leave) == "last_owner"


async def test_an_owner_can_remove_another_owner_until_one_remains(acme: Acme) -> None:
    await _set_role(acme, OWNER, ADMIN, "owner")
    assert (
        await acme.api.delete(OWNER, f"{acme.base}/members/{acme.uid(ADMIN)}")
    ).status_code == 204
    leave = await acme.api.delete(OWNER, f"{acme.base}/members/{acme.uid(OWNER)}")
    assert leave.status_code == 409 and _code(leave) == "last_owner"


async def test_removing_members_follows_the_role_hierarchy(acme: Acme) -> None:
    await acme.api.add_member(acme.org_id, "admin2@acme.example.com", "admin")
    # developers and members cannot remove anyone else
    for actor, target in ((DEV, MEMBER), (MEMBER, DEV)):
        response = await acme.api.delete(actor, f"{acme.base}/members/{acme.uid(target)}")
        assert response.status_code == 403 and _code(response) == "forbidden"
    # an admin cannot remove another admin or the owner
    for target in ("admin2@acme.example.com", OWNER):
        response = await acme.api.delete(ADMIN, f"{acme.base}/members/{acme.uid(target)}")
        assert response.status_code == 403 and _code(response) == "insufficient_role"
    # but can remove developers and members
    for target in (DEV, MEMBER):
        response = await acme.api.delete(ADMIN, f"{acme.base}/members/{acme.uid(target)}")
        assert response.status_code == 204


async def test_a_removed_member_loses_access(acme: Acme) -> None:
    assert (await acme.api.get(MEMBER, acme.base)).status_code == 200
    await acme.api.delete(OWNER, f"{acme.base}/members/{acme.uid(MEMBER)}")
    assert (await acme.api.get(MEMBER, acme.base)).status_code == 404
    assert (await acme.api.get(MEMBER, "/api/v1/organizations")).json()["total"] == 0


async def test_anyone_can_leave(acme: Acme) -> None:
    response = await acme.api.delete(MEMBER, f"{acme.base}/members/{acme.uid(MEMBER)}")
    assert response.status_code == 204
    assert (await acme.api.get(MEMBER, acme.base)).status_code == 404


async def test_removing_a_non_member_is_a_404(acme: Acme) -> None:
    response = await acme.api.delete(OWNER, f"{acme.base}/members/{acme.uid(STRANGER)}")
    assert response.status_code == 404 and _code(response) == "member_not_found"


async def test_actions_are_recorded_in_the_audit_log(acme: Acme) -> None:
    await _set_role(acme, OWNER, MEMBER, "developer")
    await acme.api.delete(OWNER, f"{acme.base}/members/{acme.uid(DEV)}")
    await acme.api.patch(OWNER, acme.base, json={"name": "Acme Corp"})
    with acme.api.owner.connect() as conn:
        from sqlalchemy import text

        rows = conn.execute(
            text("SELECT action FROM audit_logs WHERE org_id = :o"), {"o": acme.org_id}
        ).all()
    actions = {row[0] for row in rows}
    assert {
        "organization.created",
        "member.role_changed",
        "member.removed",
        "organization.updated",
    } <= actions
