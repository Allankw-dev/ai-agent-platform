"""Invitations: creating, listing, revoking and accepting, through the real API."""

from dataclasses import dataclass
from typing import Any

import pytest

from tests.integration.api_helpers import Api

OWNER = "owner@acme.example.com"
ADMIN = "admin@acme.example.com"
DEV = "dev@acme.example.com"
MEMBER = "member@acme.example.com"
STRANGER = "stranger@other.example.com"
NEWBIE = "newbie@example.com"


@dataclass
class Acme:
    api: Api
    org_id: str

    @property
    def base(self) -> str:
        return f"/api/v1/organizations/{self.org_id}"

    async def invite(self, actor: str, email: str, role: str = "member") -> Any:
        return await self.api.post(
            actor, f"{self.base}/invitations", json={"email": email, "role": role}
        )

    @staticmethod
    def token_of(created: Any) -> str:
        return str(created.json()["invite_url"]).rsplit("/invite/", 1)[1]

    async def accept(self, who: str, token: str) -> Any:
        return await self.api.post(who, "/api/v1/invitations/accept", json={"token": token})


@pytest.fixture
async def acme(api: Api) -> Acme:
    org = await api.create_org(OWNER, "Acme Inc")
    await api.add_member(org["id"], ADMIN, "admin")
    await api.add_member(org["id"], DEV, "developer")
    await api.add_member(org["id"], MEMBER, "member")
    await api.create_org(STRANGER, "Other Co")
    return Acme(api=api, org_id=org["id"])


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# ---------- creating ----------


async def test_admin_can_invite_and_gets_a_one_time_link(acme: Acme) -> None:
    response = await acme.invite(ADMIN, NEWBIE, "developer")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending" and body["role"] == "developer"
    assert "/invite/" in body["invite_url"]
    assert len(Acme.token_of(response)) >= 40


async def test_listing_never_reveals_tokens(acme: Acme) -> None:
    await acme.invite(ADMIN, NEWBIE)
    listing = (await acme.api.get(ADMIN, f"{acme.base}/invitations")).json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["email"] == NEWBIE and item["status"] == "pending"
    assert "invite_url" not in item and "token" not in item and "token_hash" not in item


async def test_only_a_hash_of_the_token_is_stored(acme: Acme) -> None:
    created = await acme.invite(ADMIN, NEWBIE)
    token = acme.token_of(created)
    stored = acme.api.scalar("SELECT token_hash FROM organization_invitations")
    assert stored != token and len(stored) == 64
    assert token not in str(
        acme.api.scalar("SELECT row_to_json(i)::text FROM organization_invitations i")
    )


@pytest.mark.parametrize("actor", [DEV, MEMBER])
async def test_developers_and_members_cannot_invite(acme: Acme, actor: str) -> None:
    response = await acme.invite(actor, NEWBIE)
    assert response.status_code == 403 and _code(response) == "forbidden"


async def test_nobody_can_invite_above_their_own_level(acme: Acme) -> None:
    response = await acme.invite(ADMIN, NEWBIE, "admin")
    assert response.status_code == 403 and _code(response) == "insufficient_role"
    assert (await acme.invite(OWNER, NEWBIE, "admin")).status_code == 201


async def test_ownership_cannot_be_granted_by_invitation(acme: Acme) -> None:
    response = await acme.invite(OWNER, NEWBIE, "owner")
    assert response.status_code == 422 and _code(response) == "validation_error"


async def test_invalid_email_is_rejected(acme: Acme) -> None:
    assert (await acme.invite(ADMIN, "not-an-email")).status_code == 422


async def test_duplicate_pending_invitations_are_refused(acme: Acme) -> None:
    assert (await acme.invite(ADMIN, NEWBIE)).status_code == 201
    for email in (NEWBIE, NEWBIE.upper()):
        again = await acme.invite(ADMIN, email)
        assert again.status_code == 409 and _code(again) == "invitation_pending"


async def test_existing_members_cannot_be_invited(acme: Acme) -> None:
    response = await acme.invite(ADMIN, MEMBER)
    assert response.status_code == 409 and _code(response) == "already_member"


async def test_non_members_cannot_see_or_create_invitations(acme: Acme) -> None:
    await acme.invite(ADMIN, NEWBIE)
    assert (await acme.api.get(STRANGER, f"{acme.base}/invitations")).status_code == 404
    assert (await acme.invite(STRANGER, "x@y.example.com")).status_code == 404


# ---------- accepting ----------


async def test_accepting_an_invitation_joins_the_organization(acme: Acme) -> None:
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE, "developer"))
    response = await acme.accept(NEWBIE, token)
    assert response.status_code == 200
    assert response.json()["role"] == "developer"
    assert response.json()["organization"]["id"] == acme.org_id

    org = await acme.api.get(NEWBIE, acme.base)
    assert org.status_code == 200 and org.json()["role"] == "developer"
    members = (await acme.api.get(OWNER, f"{acme.base}/members")).json()
    assert NEWBIE in {m["email"] for m in members["items"]}
    listing = (await acme.api.get(ADMIN, f"{acme.base}/invitations")).json()
    assert listing["items"][0]["status"] == "accepted"


async def test_an_invitation_works_only_once(acme: Acme) -> None:
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE))
    assert (await acme.accept(NEWBIE, token)).status_code == 200
    again = await acme.accept(NEWBIE, token)
    assert again.status_code in (409, 410)


async def test_someone_else_cannot_use_my_invitation(acme: Acme) -> None:
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE))
    response = await acme.accept(STRANGER, token)
    assert response.status_code == 403 and _code(response) == "invitation_email_mismatch"
    assert (await acme.api.get(STRANGER, acme.base)).status_code == 404
    # the rightful invitee can still accept afterwards
    assert (await acme.accept(NEWBIE, token)).status_code == 200


async def test_email_matching_ignores_case(acme: Acme) -> None:
    token = Acme.token_of(await acme.invite(ADMIN, "Mixed.Case@Example.com"))
    assert (await acme.accept("mixed.case@example.com", token)).status_code == 200


async def test_unknown_tokens_are_rejected(acme: Acme) -> None:
    response = await acme.accept(NEWBIE, "x" * 43)
    assert response.status_code == 404 and _code(response) == "invitation_not_found"
    assert (await acme.accept(NEWBIE, "short")).status_code == 422


async def test_expired_invitations_are_rejected_and_can_be_reissued(acme: Acme) -> None:
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE))
    acme.api.execute("UPDATE organization_invitations SET expires_at = now() - interval '1 hour'")
    response = await acme.accept(NEWBIE, token)
    assert response.status_code == 410 and _code(response) == "invitation_expired"
    listing = (await acme.api.get(ADMIN, f"{acme.base}/invitations")).json()
    assert listing["items"][0]["status"] == "expired"
    # an expired invitation no longer blocks inviting the same address again
    assert (await acme.invite(ADMIN, NEWBIE)).status_code == 201


async def test_revoked_invitations_cannot_be_accepted(acme: Acme) -> None:
    created = await acme.invite(ADMIN, NEWBIE)
    token, invitation_id = Acme.token_of(created), created.json()["id"]
    revoke = await acme.api.delete(ADMIN, f"{acme.base}/invitations/{invitation_id}")
    assert revoke.status_code == 204
    response = await acme.accept(NEWBIE, token)
    assert response.status_code == 410 and _code(response) == "invitation_not_pending"
    again = await acme.api.delete(ADMIN, f"{acme.base}/invitations/{invitation_id}")
    assert again.status_code == 409 and _code(again) == "invitation_not_pending"


async def test_revoking_requires_member_management_rights(acme: Acme) -> None:
    invitation_id = (await acme.invite(ADMIN, NEWBIE)).json()["id"]
    response = await acme.api.delete(DEV, f"{acme.base}/invitations/{invitation_id}")
    assert response.status_code == 403 and _code(response) == "forbidden"


async def test_unknown_invitation_cannot_be_revoked(acme: Acme) -> None:
    response = await acme.api.delete(
        ADMIN, f"{acme.base}/invitations/6f2b1c1e-0000-4000-8000-000000000000"
    )
    assert response.status_code == 404 and _code(response) == "invitation_not_found"


async def test_another_organizations_admin_cannot_revoke_my_invitation(acme: Acme) -> None:
    invitation_id = (await acme.invite(ADMIN, NEWBIE)).json()["id"]
    other = (await acme.api.get(STRANGER, "/api/v1/organizations")).json()["items"][0]["id"]
    response = await acme.api.delete(
        STRANGER, f"/api/v1/organizations/{other}/invitations/{invitation_id}"
    )
    assert response.status_code == 404
    listing = (await acme.api.get(ADMIN, f"{acme.base}/invitations")).json()
    assert listing["items"][0]["status"] == "pending"


async def test_someone_who_already_joined_cannot_accept(acme: Acme) -> None:
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE))
    await acme.api.add_member(acme.org_id, NEWBIE, "member")  # joined another way meanwhile
    response = await acme.accept(NEWBIE, token)
    assert response.status_code == 409 and _code(response) == "already_member"


async def test_invitation_activity_is_audited(acme: Acme) -> None:
    created = await acme.invite(ADMIN, NEWBIE)
    await acme.accept(NEWBIE, Acme.token_of(created))
    other = await acme.invite(ADMIN, "second@example.com")
    await acme.api.delete(ADMIN, f"{acme.base}/invitations/{other.json()['id']}")
    from sqlalchemy import text

    with acme.api.owner.connect() as conn:
        rows = conn.execute(
            text("SELECT action FROM audit_logs WHERE org_id = :o"), {"o": acme.org_id}
        ).all()
    assert {"invitation.created", "invitation.accepted", "invitation.revoked"} <= {
        r[0] for r in rows
    }


# ---------- the email must be confirmed with the Auth server ----------


async def test_an_unconfirmed_email_cannot_accept_an_invitation(acme: Acme) -> None:
    """Without email confirmation, anyone could register an invited address and walk in."""
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE))
    acme.api.auth_server.unconfirmed.add(NEWBIE)

    response = await acme.accept(NEWBIE, token)
    assert response.status_code == 403 and _code(response) == "email_not_confirmed"
    assert (await acme.api.get(NEWBIE, acme.base)).status_code == 404  # not a member
    listing = (await acme.api.get(ADMIN, f"{acme.base}/invitations")).json()
    assert listing["items"][0]["status"] == "pending"  # the invitation was not consumed

    acme.api.auth_server.unconfirmed.clear()  # they confirm their address
    assert (await acme.accept(NEWBIE, token)).status_code == 200


async def test_the_auth_server_must_agree_with_the_token_about_who_this_is(acme: Acme) -> None:
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE))
    acme.api.auth_server.reports_other_email[NEWBIE] = "someone-else@example.com"
    response = await acme.accept(NEWBIE, token)
    assert response.status_code == 401 and _code(response) == "invalid_token"
    assert (await acme.api.get(NEWBIE, acme.base)).status_code == 404


async def test_accepting_fails_closed_when_the_auth_server_is_down(acme: Acme) -> None:
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE))
    acme.api.auth_server.down = True
    response = await acme.accept(NEWBIE, token)
    assert response.status_code == 503 and _code(response) == "auth_unavailable"
    assert (await acme.api.get(NEWBIE, acme.base)).status_code == 404


async def test_only_accepting_an_invitation_calls_the_auth_server(acme: Acme) -> None:
    server = acme.api.auth_server
    await acme.api.get(OWNER, "/api/v1/organizations")
    await acme.api.get(OWNER, f"{acme.base}/members")
    token = Acme.token_of(await acme.invite(ADMIN, NEWBIE))
    assert server.calls == 0  # ordinary requests never pay for the extra round trip

    assert (await acme.accept(NEWBIE, token)).status_code == 200
    assert server.calls == 1
