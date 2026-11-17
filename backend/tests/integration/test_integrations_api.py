"""Integrations and their secrets, through the real API and a real database.

The rule under test: a secret goes in, encrypted, and never comes out. Not in a response, not in
an error, not in the audit log, not in the logs, and not to anyone but server-side tool code.
"""

import base64
import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.vault import VaultDecryptError, generate_key
from app.db.tenancy import use_tenant
from app.services.credentials import reveal_secret
from tests.integration.engine_helpers import ADMIN, DEV, MEMBER, OWNER, STRANGER, Workspace

Maker = async_sessionmaker[AsyncSession]

SECRET = "xoxb-1234567890-SUPER-SECRET-bot-token"
NEW_SECRET = "xoxb-9876543210-REPLACEMENT-bot-token"
SLACK = {"provider": "slack", "name": "Team Slack", "config": {"allowed_channels": ["C0123456789"]}}
HTTP = {
    "provider": "http",
    "name": "Weather API",
    "config": {"allowed_hosts": ["api.weather.example.com"]},
}


@pytest.fixture
def vault_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Give the server an encryption key for the duration of a test."""
    key = generate_key()
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    return key


@pytest.fixture(autouse=True)
def _reset_settings() -> Any:
    yield
    get_settings.cache_clear()


def url(ws: Workspace, integration_id: str | None = None, tail: str = "") -> str:
    base = f"{ws.base}/integrations"
    return f"{base}/{integration_id}{tail}" if integration_id else base


async def create(ws: Workspace, body: dict[str, Any] | None = None, who: str = ADMIN) -> str:
    response = await ws.api.post(who, url(ws), json=body or SLACK)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def save_secret(
    ws: Workspace, integration_id: str, secret: str = SECRET, who: str = ADMIN
) -> httpx.Response:
    return await ws.api.request(
        who, "PUT", url(ws, integration_id, "/credential"), json={"secret": secret}
    )


def audit_text(ws: Workspace) -> str:
    return str(
        ws.api.scalar(
            "SELECT coalesce(string_agg(action || ' ' || details::text, E'\\n'), '') FROM audit_logs"
        )
    )


def actions(ws: Workspace) -> list[str]:
    return [
        row
        for row in str(
            ws.api.scalar(
                "SELECT coalesce(string_agg(action, ',' ORDER BY created_at, id), '') "
                "FROM audit_logs WHERE action LIKE 'integration.%' OR action LIKE 'credential.%'"
            )
        ).split(",")
        if row
    ]


# ---------- who may do what ----------


async def test_owners_and_admins_can_create_integrations(workspace: Workspace) -> None:
    for who, name in [(OWNER, "From owner"), (ADMIN, "From admin")]:
        response = await workspace.api.post(who, url(workspace), json={**SLACK, "name": name})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == name
        assert body["status"] == "active"
        assert body["has_credential"] is False


@pytest.mark.parametrize("who", [DEV, MEMBER])
async def test_developers_and_members_cannot_change_integrations(
    workspace: Workspace, who: str, vault_key: str
) -> None:
    integration_id = await create(workspace)
    api = workspace.api
    assert (await api.post(who, url(workspace), json=SLACK)).status_code == 403
    assert (
        await api.patch(who, url(workspace, integration_id), json={"name": "x" * 3})
    ).status_code == 403
    assert (await api.delete(who, url(workspace, integration_id))).status_code == 403
    assert (await save_secret(workspace, integration_id, who=who)).status_code == 403
    assert (await api.delete(who, url(workspace, integration_id, "/credential"))).status_code == 403
    # ...and nothing was saved by the refused attempts.
    assert api.scalar("SELECT count(*) FROM credentials") == 0


async def test_developers_can_see_integrations_but_members_cannot(workspace: Workspace) -> None:
    integration_id = await create(workspace)
    api = workspace.api
    listing = await api.get(DEV, url(workspace))
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [integration_id]
    assert (await api.get(DEV, url(workspace, integration_id))).status_code == 200
    assert (await api.get(MEMBER, url(workspace))).status_code == 403
    assert (await api.get(MEMBER, url(workspace, integration_id))).status_code == 403


async def test_another_organization_cannot_see_or_touch_an_integration(
    workspace: Workspace, vault_key: str
) -> None:
    integration_id = await create(workspace)
    await save_secret(workspace, integration_id)
    api = workspace.api
    theirs = f"/api/v1/organizations/{workspace.other_org_id}/integrations"

    # A stranger is not a member of the first organization at all.
    assert (await api.get(STRANGER, url(workspace))).status_code in (403, 404)
    # In their own organization the id simply does not exist.
    assert (await api.get(STRANGER, f"{theirs}/{integration_id}")).status_code == 404
    assert (
        await api.request(
            STRANGER, "PUT", f"{theirs}/{integration_id}/credential", json={"secret": "x" * 10}
        )
    ).status_code == 404
    assert (await api.delete(STRANGER, f"{theirs}/{integration_id}")).status_code == 404
    assert (await api.get(STRANGER, theirs)).json()["items"] == []
    # The original is untouched.
    assert api.scalar("SELECT count(*) FROM credentials") == 1


# ---------- creating and editing ----------


async def test_an_http_integration_keeps_cleaned_settings(workspace: Workspace) -> None:
    response = await workspace.api.post(
        ADMIN,
        url(workspace),
        json={
            "provider": "http",
            "name": "Weather API",
            "config": {"allowed_hosts": [" API.Weather.example.com "], "auth_scheme": ""},
        },
    )
    assert response.status_code == 201
    assert response.json()["config"] == {
        "allowed_hosts": ["api.weather.example.com"],
        "auth_header": "Authorization",
        "auth_scheme": "",
    }


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"provider": "github", "name": "Repo"}, "provider_not_supported"),
        (
            {"provider": "http", "name": "Bad", "config": {"allowed_hosts": ["http://x.com"]}},
            "invalid_integration_config",
        ),
        (
            {"provider": "slack", "name": "Bad", "config": {"allowed_channels": ["general"]}},
            "invalid_integration_config",
        ),
        (
            {"provider": "slack", "name": "Bad", "config": {"allowed_hosts": ["a.example.com"]}},
            "invalid_integration_config",
        ),
    ],
)
async def test_bad_integrations_are_refused_clearly(
    workspace: Workspace, body: dict[str, Any], code: str
) -> None:
    response = await workspace.api.post(ADMIN, url(workspace), json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert workspace.api.scalar("SELECT count(*) FROM integrations") == 0


async def test_names_are_unique_per_provider(workspace: Workspace) -> None:
    await create(workspace, SLACK)
    duplicate = await workspace.api.post(OWNER, url(workspace), json=SLACK)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "integration_name_taken"
    # The same name for a different provider is fine.
    assert (
        await workspace.api.post(OWNER, url(workspace), json={**HTTP, "name": "Team Slack"})
    ).status_code == 201


async def test_editing_name_status_and_settings(workspace: Workspace) -> None:
    integration_id = await create(workspace)
    api = workspace.api
    response = await api.patch(
        ADMIN,
        url(workspace, integration_id),
        json={
            "name": "Renamed",
            "status": "disabled",
            "config": {"allowed_channels": ["c0aaaaaaaaa", "G0bbbbbbbbb"]},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["status"]) == ("Renamed", "disabled")
    assert body["config"] == {"allowed_channels": ["C0AAAAAAAAA", "G0BBBBBBBBB"]}
    assert (await api.patch(ADMIN, url(workspace, integration_id), json={})).status_code == 422
    assert (
        await api.patch(ADMIN, url(workspace, integration_id), json={"status": "error"})
    ).status_code == 422
    missing = await api.patch(ADMIN, url(workspace, str(uuid.uuid4())), json={"name": "Nope"})
    assert missing.status_code == 404


async def test_list_filters_by_provider_and_pages(workspace: Workspace) -> None:
    await create(workspace, SLACK)
    await create(workspace, HTTP)
    api = workspace.api
    both = (await api.get(ADMIN, url(workspace))).json()
    assert both["total"] == 2
    only_http = (await api.get(ADMIN, url(workspace), params={"provider": "http"})).json()
    assert [item["provider"] for item in only_http["items"]] == ["http"]
    page = (await api.get(ADMIN, url(workspace), params={"limit": 1})).json()
    assert (len(page["items"]), page["total"]) == (1, 2)


# ---------- the secret: in, encrypted, never out ----------


async def test_a_saved_secret_is_encrypted_and_never_returned(
    workspace: Workspace, vault_key: str, capsys: pytest.CaptureFixture[str]
) -> None:
    integration_id = await create(workspace)
    api = workspace.api

    saved = await save_secret(workspace, integration_id)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["has_credential"] is True
    assert body["credential_set_by_name"] == ADMIN
    assert body["credential_updated_at"] is not None
    assert SECRET not in saved.text

    # Every way of reading it back shows only the fact that a secret exists.
    for who in (OWNER, ADMIN, DEV):
        for path in (url(workspace), url(workspace, integration_id)):
            response = await api.get(who, path)
            assert response.status_code == 200
            assert SECRET not in response.text
            assert "encrypted" not in response.text and "payload" not in response.text
    assert (await api.get(ADMIN, url(workspace, integration_id))).json()["has_credential"] is True

    # In the database it is ciphertext: not the secret, not even a piece of it.
    stored = bytes(
        api.scalar(
            "SELECT encrypted_payload FROM credentials WHERE integration_id = :i", i=integration_id
        )
    )
    assert SECRET.encode() not in stored
    assert b"xoxb" not in stored
    assert api.scalar("SELECT key_version FROM credentials") == 1

    # Not in the audit log, and not in anything printed by the server.
    assert SECRET not in audit_text(workspace)
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


async def test_replacing_a_secret_updates_the_one_row(workspace: Workspace, vault_key: str) -> None:
    integration_id = await create(workspace)
    await save_secret(workspace, integration_id)
    before = bytes(workspace.api.scalar("SELECT encrypted_payload FROM credentials"))

    replaced = await save_secret(workspace, integration_id, NEW_SECRET, who=OWNER)
    assert replaced.status_code == 200
    assert replaced.json()["credential_set_by_name"] == OWNER
    assert workspace.api.scalar("SELECT count(*) FROM credentials") == 1
    assert bytes(workspace.api.scalar("SELECT encrypted_payload FROM credentials")) != before
    assert actions(workspace) == [
        "integration.created",
        "credential.added",
        "credential.replaced",
    ]
    assert NEW_SECRET not in audit_text(workspace) and SECRET not in audit_text(workspace)


async def test_the_secret_can_be_removed(workspace: Workspace, vault_key: str) -> None:
    integration_id = await create(workspace)
    await save_secret(workspace, integration_id)
    api = workspace.api
    assert (
        await api.delete(ADMIN, url(workspace, integration_id, "/credential"))
    ).status_code == 204
    assert api.scalar("SELECT count(*) FROM credentials") == 0
    assert (await api.get(ADMIN, url(workspace, integration_id))).json()["has_credential"] is False
    again = await api.delete(ADMIN, url(workspace, integration_id, "/credential"))
    assert again.status_code == 404
    assert actions(workspace)[-1] == "credential.removed"


async def test_deleting_an_integration_deletes_its_secret(
    workspace: Workspace, vault_key: str
) -> None:
    integration_id = await create(workspace)
    await save_secret(workspace, integration_id)
    assert (await workspace.api.delete(OWNER, url(workspace, integration_id))).status_code == 204
    assert workspace.api.scalar("SELECT count(*) FROM credentials") == 0
    assert workspace.api.scalar("SELECT count(*) FROM integrations") == 0
    assert actions(workspace)[-1] == "integration.deleted"
    assert (await workspace.api.get(ADMIN, url(workspace, integration_id))).status_code == 404


async def test_every_change_is_audited_without_the_secret(
    workspace: Workspace, vault_key: str
) -> None:
    integration_id = await create(workspace)
    api = workspace.api
    await api.patch(ADMIN, url(workspace, integration_id), json={"status": "disabled"})
    await save_secret(workspace, integration_id)
    await api.delete(ADMIN, url(workspace, integration_id, "/credential"))
    await api.delete(ADMIN, url(workspace, integration_id))
    assert actions(workspace) == [
        "integration.created",
        "integration.updated",
        "credential.added",
        "credential.removed",
        "integration.deleted",
    ]
    assert SECRET not in audit_text(workspace)
    assert (
        api.scalar(
            "SELECT count(*) FROM audit_logs WHERE actor_user_id IS NULL AND action LIKE 'credential.%'"
        )
        == 0
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"secret": "x" * 5_000},
        {"secret": SECRET, "extra": "field"},
        {"secret": ""},
        {"secret": ["a", SECRET]},
        {"token": SECRET},
    ],
)
async def test_a_rejected_secret_is_never_echoed_back(
    workspace: Workspace, vault_key: str, payload: dict[str, Any]
) -> None:
    integration_id = await create(workspace)
    response = await workspace.api.request(
        ADMIN, "PUT", url(workspace, integration_id, "/credential"), json=payload
    )
    assert response.status_code == 422
    assert SECRET not in response.text
    assert "x" * 100 not in response.text
    assert workspace.api.scalar("SELECT count(*) FROM credentials") == 0


async def test_without_an_encryption_key_nothing_is_saved(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(get_settings(), "credential_encryption_key", None)
    integration_id = await create(workspace)  # everything else still works
    response = await save_secret(workspace, integration_id)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "credentials_not_configured"
    assert "CREDENTIAL_ENCRYPTION_KEY" in response.json()["error"]["message"]
    assert SECRET not in response.text
    assert workspace.api.scalar("SELECT count(*) FROM credentials") == 0
    assert (await workspace.api.get(ADMIN, url(workspace))).status_code == 200


async def test_an_unusable_key_is_refused_without_saving(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", base64.b64encode(b"too short").decode())
    get_settings.cache_clear()
    integration_id = await create(workspace)
    response = await save_secret(workspace, integration_id)
    assert response.status_code == 503
    assert workspace.api.scalar("SELECT count(*) FROM credentials") == 0


# ---------- reading the secret back, server side only ----------


async def reveal(maker: Maker, org_id: str, integration_id: str) -> str | None:
    async with maker() as session:
        await use_tenant(session, org_id=uuid.UUID(org_id))
        return await reveal_secret(session, uuid.UUID(org_id), uuid.UUID(integration_id))


async def test_server_side_code_can_read_the_secret_back(
    workspace: Workspace, runtime_maker: Maker, vault_key: str
) -> None:
    integration_id = await create(workspace)
    assert await reveal(runtime_maker, workspace.org_id, integration_id) is None  # none saved yet
    await save_secret(workspace, integration_id)
    assert await reveal(runtime_maker, workspace.org_id, integration_id) == SECRET
    await save_secret(workspace, integration_id, NEW_SECRET)
    assert await reveal(runtime_maker, workspace.org_id, integration_id) == NEW_SECRET


async def test_another_organization_cannot_read_the_secret(
    workspace: Workspace, runtime_maker: Maker, vault_key: str
) -> None:
    integration_id = await create(workspace)
    await save_secret(workspace, integration_id)
    # Asking as the other organization finds nothing: Row Level Security hides the row.
    assert await reveal(runtime_maker, workspace.other_org_id, integration_id) is None


async def test_a_ciphertext_copied_to_another_integration_does_not_decrypt(
    workspace: Workspace, runtime_maker: Maker, vault_key: str
) -> None:
    first = await create(workspace, SLACK)
    second = await create(workspace, HTTP)
    await save_secret(workspace, first)
    await save_secret(workspace, second, NEW_SECRET)
    api = workspace.api
    api.execute(
        "UPDATE credentials SET encrypted_payload = "
        "(SELECT encrypted_payload FROM credentials WHERE integration_id = :a) "
        "WHERE integration_id = :b",
        a=first,
        b=second,
    )
    with pytest.raises(VaultDecryptError):
        await reveal(runtime_maker, workspace.org_id, second)
    assert await reveal(runtime_maker, workspace.org_id, first) == SECRET


async def test_a_tampered_or_foreign_key_value_does_not_decrypt(
    workspace: Workspace, runtime_maker: Maker, vault_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    integration_id = await create(workspace)
    await save_secret(workspace, integration_id)
    api = workspace.api

    # One flipped bit in the stored value.
    api.execute(
        "UPDATE credentials SET encrypted_payload = set_byte(encrypted_payload, 20, "
        "get_byte(encrypted_payload, 20) # 1)"
    )
    with pytest.raises(VaultDecryptError):
        await reveal(runtime_maker, workspace.org_id, integration_id)

    # A server restarted with a different key cannot read what the old key wrote.
    await save_secret(workspace, integration_id)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", generate_key())
    get_settings.cache_clear()
    with pytest.raises(VaultDecryptError) as caught:
        await reveal(runtime_maker, workspace.org_id, integration_id)
    assert SECRET not in str(caught.value)


async def test_no_endpoint_returns_a_secret_in_any_form(
    workspace: Workspace, vault_key: str
) -> None:
    """Walk every integrations route as every role and look for the secret in the replies."""
    integration_id = await create(workspace)
    await save_secret(workspace, integration_id)
    api = workspace.api
    seen = []
    for who in (OWNER, ADMIN, DEV, MEMBER):
        for method, path in [
            ("GET", url(workspace)),
            ("GET", url(workspace, integration_id)),
            ("GET", url(workspace, integration_id, "/credential")),
            ("PATCH", url(workspace, integration_id)),
        ]:
            response = await api.request(
                who, method, path, json={"name": "Again"} if method == "PATCH" else None
            )
            seen.append(response.text)
    blob = json.dumps(seen)
    assert SECRET not in blob
    assert base64.b64encode(SECRET.encode()).decode() not in blob
