"""Agents and their versions, through the real API as the restricted database role."""

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text

from tests.integration.api_helpers import Api

OWNER = "owner@acme.example.com"
ADMIN = "admin@acme.example.com"
DEV = "dev@acme.example.com"
MEMBER = "member@acme.example.com"
STRANGER = "stranger@other.example.com"


def config(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "provider": "gemini",
        "model": "gemini-flash-latest",
        "system_instructions": "You are a careful support assistant.",
        "tools": [],
    }
    base.update(overrides)
    return base


@dataclass
class Studio:
    api: Api
    org_id: str

    @property
    def base(self) -> str:
        return f"/api/v1/organizations/{self.org_id}/agents"

    async def create(
        self,
        who: str = DEV,
        name: str = "Support bot",
        description: str | None = None,
        **cfg: Any,
    ) -> dict[str, Any]:
        body = {"name": name, "description": description, "config": config(**cfg)}
        response = await self.api.post(who, self.base, json=body)
        assert response.status_code == 201, response.text
        return dict(response.json())


@pytest.fixture
async def studio(api: Api) -> Studio:
    org = await api.create_org(OWNER, "Acme Inc")
    await api.add_member(org["id"], ADMIN, "admin")
    await api.add_member(org["id"], DEV, "developer")
    await api.add_member(org["id"], MEMBER, "member")
    await api.create_org(STRANGER, "Other Co")
    return Studio(api=api, org_id=org["id"])


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# ---------- creating ----------


async def test_creating_an_agent_makes_a_draft_with_version_one(studio: Studio) -> None:
    agent = await studio.create(
        description="Answers support questions",
        tools=[{"tool_key": "utility.current_time"}, {"tool_key": "utility.calculate"}],
        objectives="Resolve tickets politely.",
    )
    assert agent["status"] == "draft"
    version = agent["current_version"]
    assert version["version"] == 1 and version["provider"] == "gemini"
    assert version["change_note"] == "Initial version"
    assert version["limits"]["max_iterations"] == 10
    assert {t["tool_key"] for t in version["tools"]} == {
        "utility.current_time",
        "utility.calculate",
    }


@pytest.mark.parametrize(("who", "status"), [(OWNER, 201), (ADMIN, 201), (DEV, 201), (MEMBER, 403)])
async def test_who_can_create_agents(studio: Studio, who: str, status: int) -> None:
    response = await studio.api.post(who, studio.base, json={"name": "A bot", "config": config()})
    assert response.status_code == status
    if status == 403:
        assert _code(response) == "forbidden"


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"tools": [{"tool_key": "nope.missing"}]}, "unknown_tool"),
        ({"provider": "anthropic"}, "provider_not_enabled"),
        ({"limits": {"max_iterations": 26}}, "limit_exceeds_platform_maximum"),
        ({"limits": {"timeout_seconds": 301}}, "limit_exceeds_platform_maximum"),
        ({"limits": {"max_total_tokens": 500_001}}, "limit_exceeds_platform_maximum"),
        ({"limits": {"cost_budget_usd": 5.01}}, "limit_exceeds_platform_maximum"),
        ({"system_instructions": " "}, "validation_error"),
        ({"model_params": {"temperature": 0.5}}, "validation_error"),
        ({"model": "bad model"}, "validation_error"),
    ],
)
async def test_invalid_configurations_are_refused(
    studio: Studio, override: dict[str, Any], code: str
) -> None:
    response = await studio.api.post(
        DEV, studio.base, json={"name": "A bot", "config": config(**override)}
    )
    assert response.status_code == 422 and _code(response) == code


async def test_limits_at_the_platform_ceiling_are_allowed(studio: Studio) -> None:
    limits = {
        "max_iterations": 25,
        "timeout_seconds": 300,
        "max_total_tokens": 500_000,
        "cost_budget_usd": 5.0,
    }
    agent = await studio.create(limits=limits)
    assert agent["current_version"]["limits"] == limits


async def test_agent_names_are_unique_per_organization(studio: Studio) -> None:
    first = await studio.create(name="Support bot")
    clash = await studio.api.post(
        DEV, studio.base, json={"name": "Support bot", "config": config()}
    )
    assert clash.status_code == 409 and _code(clash) == "agent_name_taken"

    # a deleted agent frees its name, and other organizations are independent
    await studio.api.delete(DEV, f"{studio.base}/{first['id']}")
    await studio.create(name="Support bot")
    other = (await studio.api.get(STRANGER, "/api/v1/organizations")).json()["items"][0]["id"]
    other_base = f"/api/v1/organizations/{other}/agents"
    response = await studio.api.post(
        STRANGER, other_base, json={"name": "Support bot", "config": config()}
    )
    assert response.status_code == 201


async def test_sensitive_tools_always_require_approval(studio: Studio) -> None:
    studio.api.execute(
        "INSERT INTO tools (key, name, description, input_schema, is_sensitive) "
        "VALUES ('test.dangerous', 'Dangerous', 'x', CAST('{}' AS jsonb), true)"
    )
    agent = await studio.create(
        tools=[
            {"tool_key": "test.dangerous", "requires_approval": False},
            {"tool_key": "utility.calculate", "requires_approval": False},
        ]
    )
    tools = {t["tool_key"]: t for t in agent["current_version"]["tools"]}
    assert tools["test.dangerous"]["requires_approval"] is True  # cannot be switched off
    assert tools["utility.calculate"]["requires_approval"] is False


# ---------- reading ----------


async def test_every_member_can_read_agents_but_only_their_own_organizations(
    studio: Studio,
) -> None:
    agent = await studio.create()
    for who in (OWNER, ADMIN, DEV, MEMBER):
        assert (await studio.api.get(who, f"{studio.base}/{agent['id']}")).status_code == 200
        assert (await studio.api.get(who, studio.base)).json()["total"] == 1
    assert (await studio.api.get(STRANGER, studio.base)).status_code == 404
    assert (await studio.api.get(STRANGER, f"{studio.base}/{agent['id']}")).status_code == 404


async def test_listing_filters_searches_and_paginates(studio: Studio) -> None:
    a = await studio.create(name="Alpha bot")
    await studio.create(name="Beta bot")
    await studio.create(name="100% legit_bot")
    await studio.api.patch(DEV, f"{studio.base}/{a['id']}", json={"status": "active"})

    everything = (await studio.api.get(MEMBER, studio.base)).json()
    assert everything["total"] == 3
    active = (await studio.api.get(MEMBER, studio.base, params={"status": "active"})).json()
    assert [i["name"] for i in active["items"]] == ["Alpha bot"]
    found = (await studio.api.get(MEMBER, studio.base, params={"q": "BETA"})).json()
    assert [i["name"] for i in found["items"]] == ["Beta bot"]
    # LIKE wildcards in a search are literal characters, not patterns
    percent = (await studio.api.get(MEMBER, studio.base, params={"q": "100%"})).json()
    assert [i["name"] for i in percent["items"]] == ["100% legit_bot"]
    assert (await studio.api.get(MEMBER, studio.base, params={"q": "%"})).json()["total"] == 1
    page = (await studio.api.get(MEMBER, studio.base, params={"limit": 2})).json()
    assert len(page["items"]) == 2 and page["total"] == 3
    assert (await studio.api.get(MEMBER, studio.base, params={"limit": 0})).status_code == 422
    assert (
        await studio.api.get(MEMBER, studio.base, params={"status": "bogus"})
    ).status_code == 422
    assert everything["items"][0]["current_version"]["version"] == 1


async def test_unknown_agent_is_a_404(studio: Studio) -> None:
    response = await studio.api.get(DEV, f"{studio.base}/6f2b1c1e-0000-4000-8000-000000000000")
    assert response.status_code == 404 and _code(response) == "agent_not_found"


# ---------- updating ----------


async def test_renaming_describing_enabling_and_disabling(studio: Studio) -> None:
    agent = await studio.create()
    url = f"{studio.base}/{agent['id']}"
    changed = await studio.api.patch(DEV, url, json={"name": "New name", "description": "Hello"})
    assert changed.json()["name"] == "New name" and changed.json()["description"] == "Hello"
    assert (await studio.api.patch(DEV, url, json={"status": "active"})).json()[
        "status"
    ] == "active"
    assert (await studio.api.patch(DEV, url, json={"status": "disabled"})).json()[
        "status"
    ] == "disabled"
    cleared = await studio.api.patch(DEV, url, json={"description": None})
    assert cleared.json()["description"] is None


async def test_invalid_updates_are_refused(studio: Studio) -> None:
    a = await studio.create(name="First bot")
    await studio.create(name="Second bot")
    url = f"{studio.base}/{a['id']}"
    assert (await studio.api.patch(DEV, url, json={})).status_code == 422
    assert (await studio.api.patch(DEV, url, json={"status": "archived"})).status_code == 422
    clash = await studio.api.patch(DEV, url, json={"name": "Second bot"})
    assert clash.status_code == 409 and _code(clash) == "agent_name_taken"
    assert (await studio.api.patch(MEMBER, url, json={"name": "Hijack"})).status_code == 403


# ---------- versions ----------


async def test_editing_creates_a_new_version_and_keeps_the_old_one_intact(studio: Studio) -> None:
    agent = await studio.create(system_instructions="Original instructions.")
    url = f"{studio.base}/{agent['id']}"
    response = await studio.api.post(
        DEV,
        f"{url}/versions",
        json={
            "config": config(system_instructions="Updated instructions.", model="gemini-other"),
            "change_note": "Switch model",
        },
    )
    assert response.status_code == 201
    assert response.json()["version"] == 2 and response.json()["change_note"] == "Switch model"

    current = (await studio.api.get(DEV, url)).json()["current_version"]
    assert current["version"] == 2 and current["model"] == "gemini-other"
    old = (await studio.api.get(DEV, f"{url}/versions/1")).json()
    assert old["system_instructions"] == "Original instructions."

    history = (await studio.api.get(MEMBER, f"{url}/versions")).json()
    assert [v["version"] for v in history["items"]] == [2, 1]
    assert "system_instructions" not in history["items"][0]  # summaries only


async def test_concurrent_edits_never_collide_on_version_numbers(studio: Studio) -> None:
    agent = await studio.create()
    url = f"{studio.base}/{agent['id']}/versions"
    responses = await asyncio.gather(
        *[
            studio.api.post(DEV, url, json={"config": config(system_instructions=f"Variant {i}.")})
            for i in range(5)
        ]
    )
    assert [r.status_code for r in responses] == [201] * 5
    assert sorted(r.json()["version"] for r in responses) == [2, 3, 4, 5, 6]


async def test_members_cannot_edit_versions_and_missing_things_are_404(studio: Studio) -> None:
    agent = await studio.create()
    url = f"{studio.base}/{agent['id']}"
    denied = await studio.api.post(MEMBER, f"{url}/versions", json={"config": config()})
    assert denied.status_code == 403
    missing = await studio.api.get(DEV, f"{url}/versions/99")
    assert missing.status_code == 404 and _code(missing) == "version_not_found"
    ghost = "6f2b1c1e-0000-4000-8000-000000000000"
    assert (await studio.api.get(DEV, f"{studio.base}/{ghost}/versions")).status_code == 404


async def test_invalid_new_versions_are_refused_and_change_nothing(studio: Studio) -> None:
    agent = await studio.create()
    url = f"{studio.base}/{agent['id']}"
    bad = await studio.api.post(
        DEV, f"{url}/versions", json={"config": config(tools=[{"tool_key": "nope.missing"}])}
    )
    assert bad.status_code == 422
    assert (await studio.api.get(DEV, f"{url}/versions")).json()["total"] == 1


# ---------- rollback ----------


async def test_rollback_points_the_agent_at_an_older_version(studio: Studio) -> None:
    agent = await studio.create(system_instructions="Version one.")
    url = f"{studio.base}/{agent['id']}"
    await studio.api.post(
        DEV, f"{url}/versions", json={"config": config(system_instructions="Two.")}
    )

    rolled = await studio.api.post(DEV, f"{url}/rollback", json={"version": 1})
    assert rolled.status_code == 200
    assert rolled.json()["current_version"]["system_instructions"] == "Version one."
    assert (await studio.api.get(DEV, f"{url}/versions")).json()["total"] == 2  # nothing deleted

    # the next edit continues the numbering instead of reusing a number
    third = await studio.api.post(DEV, f"{url}/versions", json={"config": config()})
    assert third.json()["version"] == 3


async def test_rollback_validation(studio: Studio) -> None:
    agent = await studio.create()
    url = f"{studio.base}/{agent['id']}/rollback"
    same = await studio.api.post(DEV, url, json={"version": 1})
    assert same.status_code == 409 and _code(same) == "already_current"
    missing = await studio.api.post(DEV, url, json={"version": 9})
    assert missing.status_code == 404 and _code(missing) == "version_not_found"
    assert (await studio.api.post(DEV, url, json={"version": 0})).status_code == 422
    assert (await studio.api.post(MEMBER, url, json={"version": 1})).status_code == 403


# ---------- duplicating ----------


async def test_duplicating_copies_the_current_configuration(studio: Studio) -> None:
    agent = await studio.create(
        name="Support bot",
        system_instructions="Be kind.",
        tools=[{"tool_key": "utility.calculate"}],
        limits={"max_iterations": 7},
    )
    url = f"{studio.base}/{agent['id']}/duplicate"
    first = await studio.api.post(DEV, url, json={})
    assert first.status_code == 201
    copy = first.json()
    assert copy["name"] == "Support bot (copy)" and copy["status"] == "draft"
    assert copy["id"] != agent["id"]
    version = copy["current_version"]
    assert version["system_instructions"] == "Be kind." and version["limits"]["max_iterations"] == 7
    assert [t["tool_key"] for t in version["tools"]] == ["utility.calculate"]
    assert version["change_note"] == "Duplicated from Support bot"

    second = await studio.api.post(DEV, url, json={})
    assert second.json()["name"] == "Support bot (copy 2)"
    named = await studio.api.post(DEV, url, json={"name": "Custom name"})
    assert named.json()["name"] == "Custom name"
    clash = await studio.api.post(DEV, url, json={"name": "Custom name"})
    assert clash.status_code == 409 and _code(clash) == "agent_name_taken"


# ---------- deleting ----------


async def test_deleting_is_soft_and_keeps_history(studio: Studio) -> None:
    agent = await studio.create()
    url = f"{studio.base}/{agent['id']}"
    assert (await studio.api.delete(MEMBER, url)).status_code == 403
    assert (await studio.api.delete(DEV, url)).status_code == 204

    assert (await studio.api.get(DEV, url)).status_code == 404
    assert (await studio.api.get(DEV, studio.base)).json()["total"] == 0
    assert (await studio.api.delete(DEV, url)).status_code == 404
    assert (await studio.api.patch(DEV, url, json={"name": "Zombie"})).status_code == 404
    row = studio.api.scalar(
        "SELECT deleted_at IS NOT NULL FROM agents WHERE id = :i", i=agent["id"]
    )
    assert row is True
    versions = studio.api.scalar(
        "SELECT count(*) FROM agent_versions WHERE agent_id = :i", i=agent["id"]
    )
    assert versions == 1


# ---------- audit and catalog ----------


async def test_agent_activity_is_audited(studio: Studio) -> None:
    agent = await studio.create()
    url = f"{studio.base}/{agent['id']}"
    await studio.api.patch(DEV, url, json={"name": "Renamed"})
    await studio.api.patch(DEV, url, json={"status": "active"})
    await studio.api.patch(DEV, url, json={"status": "disabled"})
    await studio.api.post(DEV, f"{url}/versions", json={"config": config()})
    await studio.api.post(DEV, f"{url}/rollback", json={"version": 1})
    await studio.api.post(DEV, f"{url}/duplicate", json={})
    await studio.api.delete(DEV, url)
    with studio.api.owner.connect() as conn:
        rows = conn.execute(
            text("SELECT action FROM audit_logs WHERE org_id = :o"), {"o": studio.org_id}
        ).all()
    assert {
        "agent.created",
        "agent.updated",
        "agent.enabled",
        "agent.disabled",
        "agent.version_created",
        "agent.rolled_back",
        "agent.duplicated",
        "agent.deleted",
    } <= {r[0] for r in rows}


async def test_the_tool_catalog_lists_the_built_in_tools_for_any_signed_in_user(api: Api) -> None:
    response = await api.get("nobody@example.com", "/api/v1/tools")
    assert response.status_code == 200
    tools = {t["key"]: t for t in response.json()}
    assert {"utility.current_time", "utility.calculate"} <= set(tools)
    assert tools["utility.calculate"]["input_schema"]["required"] == ["expression"]
    assert tools["utility.calculate"]["is_sensitive"] is False
