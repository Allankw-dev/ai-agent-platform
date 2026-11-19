"""Giving an agent an HTTP tool: the integration it points at is checked when the version is saved."""

import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from app.engine.gemini import to_gemini_schema
from tests.integration.engine_helpers import ADMIN, DEV, OWNER, STRANGER, Workspace, agent_config

HTTP = {"provider": "http", "name": "Weather API", "config": {"allowed_hosts": ["api.example.com"]}}
SLACK = {"provider": "slack", "name": "Team Slack", "config": {"allowed_channels": ["C0123456789"]}}


async def integration(ws: Workspace, body: dict[str, Any] = HTTP, who: str = ADMIN) -> str:
    response = await ws.api.post(who, f"{ws.base}/integrations", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def grant(key: str = "http.get", **config: Any) -> dict[str, Any]:
    return {"tool_key": key, "config": config}


async def save(ws: Workspace, *tools: dict[str, Any], who: str = DEV, name: str = "Helper") -> Any:
    return await ws.api.post(
        who,
        f"{ws.base}/agents",
        json={"name": name, "config": agent_config(tools=list(tools))},
    )


async def error_code(response: Any, status: int = 422) -> str:
    assert response.status_code == status, response.text
    return str(response.json()["error"]["code"])


def _all_types_are_text(node: Any) -> bool:
    if isinstance(node, dict):
        if "type" in node and not isinstance(node["type"], str):
            return False
        return all(_all_types_are_text(value) for value in node.values())
    if isinstance(node, list):
        return all(_all_types_are_text(item) for item in node)
    return True


# ---------- the catalog ----------


async def test_the_catalog_lists_the_http_tools_and_which_integration_they_need(
    workspace: Workspace,
) -> None:
    response = await workspace.api.get(DEV, "/api/v1/tools")
    assert response.status_code == 200
    tools = {tool["key"]: tool for tool in response.json()}
    assert tools["http.get"]["provider"] == "http" and tools["http.get"]["is_sensitive"] is False
    assert tools["http.request"]["provider"] == "http"
    assert tools["http.request"]["is_sensitive"] is True
    assert tools["utility.calculate"]["provider"] is None


async def test_the_http_tool_schemas_are_valid_and_gemini_compatible(workspace: Workspace) -> None:
    tools = {t["key"]: t for t in (await workspace.api.get(DEV, "/api/v1/tools")).json()}
    for key in ("http.get", "http.request"):
        schema = tools[key]["input_schema"]
        Draft202012Validator.check_schema(schema)
        reduced = to_gemini_schema(schema)
        assert reduced["type"] == "OBJECT"
        assert "additionalProperties" not in str(reduced)
        headers = reduced["properties"]["headers"]
        assert headers["type"] == "ARRAY" and headers["items"]["type"] == "OBJECT"
        assert set(headers["items"]["properties"]) == {"name", "value"}
        assert reduced["properties"]["url"]["type"] == "STRING"
        # Gemini rejects a type given as a list, so no schema may use one anywhere.
        assert _all_types_are_text(reduced)
    assert to_gemini_schema(tools["http.request"]["input_schema"])["properties"]["method"][
        "enum"
    ] == [
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ]


# ---------- saving a version ----------


async def test_an_agent_can_be_given_an_http_tool_with_an_integration(
    workspace: Workspace,
) -> None:
    integration_id = await integration(workspace)
    response = await save(workspace, grant(integration_id=integration_id))
    assert response.status_code == 201, response.text
    (tool,) = response.json()["current_version"]["tools"]
    assert tool["tool_key"] == "http.get" and tool["provider"] == "http"
    assert tool["config"] == {"integration_id": integration_id}
    assert tool["requires_approval"] is False


async def test_a_write_tool_always_needs_approval(workspace: Workspace) -> None:
    integration_id = await integration(workspace)
    response = await save(workspace, grant("http.request", integration_id=integration_id))
    assert response.status_code == 201
    assert response.json()["current_version"]["tools"][0]["requires_approval"] is True


async def test_both_http_tools_can_share_one_integration(workspace: Workspace) -> None:
    integration_id = await integration(workspace)
    response = await save(
        workspace,
        grant("http.get", integration_id=integration_id),
        grant("http.request", integration_id=integration_id),
    )
    assert response.status_code == 201


@pytest.mark.parametrize("config", [{}, {"integration_id": ""}, {"integration_id": None}])
async def test_an_http_tool_without_an_integration_is_refused(
    workspace: Workspace, config: dict[str, Any]
) -> None:
    response = await save(workspace, grant(**config))
    assert await error_code(response) == "integration_required"
    assert "needs an integration" in response.json()["error"]["message"]


async def test_an_integration_that_does_not_exist_is_refused(workspace: Workspace) -> None:
    response = await save(workspace, grant(integration_id=str(uuid.uuid4())))
    assert await error_code(response) == "integration_not_found"


@pytest.mark.parametrize("bad", ["not-a-uuid", 5, ["x"], {"a": 1}])
async def test_a_malformed_integration_id_is_refused(workspace: Workspace, bad: Any) -> None:
    response = await save(workspace, grant(integration_id=bad))
    assert await error_code(response) == "invalid_tool_config"


async def test_unknown_tool_settings_are_refused(workspace: Workspace) -> None:
    integration_id = await integration(workspace)
    response = await save(workspace, grant(integration_id=integration_id, allow_all=True))
    assert await error_code(response) == "invalid_tool_config"


async def test_another_organizations_integration_cannot_be_used(workspace: Workspace) -> None:
    theirs = await workspace.api.post(
        STRANGER,
        f"/api/v1/organizations/{workspace.other_org_id}/integrations",
        json=HTTP,
    )
    assert theirs.status_code == 201
    response = await save(workspace, grant(integration_id=theirs.json()["id"]))
    assert await error_code(response) == "integration_not_found"  # as if it did not exist


async def test_an_integration_of_the_wrong_type_is_refused(workspace: Workspace) -> None:
    slack_id = await integration(workspace, SLACK)
    response = await save(workspace, grant(integration_id=slack_id))
    assert await error_code(response) == "integration_wrong_type"


async def test_a_disabled_integration_is_refused(workspace: Workspace) -> None:
    integration_id = await integration(workspace)
    await workspace.api.patch(
        ADMIN, f"{workspace.base}/integrations/{integration_id}", json={"status": "disabled"}
    )
    response = await save(workspace, grant(integration_id=integration_id))
    assert await error_code(response) == "integration_disabled"


async def test_a_refused_save_creates_nothing(workspace: Workspace) -> None:
    await save(workspace, grant())
    assert workspace.api.scalar("SELECT count(*) FROM agents") == 0
    assert workspace.api.scalar("SELECT count(*) FROM agent_versions") == 0


async def test_a_tool_without_a_provider_needs_no_integration(workspace: Workspace) -> None:
    response = await save(workspace, {"tool_key": "utility.calculate"})
    assert response.status_code == 201


# ---------- later versions ----------


async def test_new_versions_check_the_integration_again_but_a_rollback_restores_history(
    workspace: Workspace,
) -> None:
    integration_id = await integration(workspace)
    created = await save(workspace, grant(integration_id=integration_id))
    agent_id = created.json()["id"]
    base = f"{workspace.base}/agents/{agent_id}"

    plain = await workspace.api.post(
        DEV, f"{base}/versions", json={"config": agent_config(tools=[])}
    )
    assert plain.status_code == 201
    assert (
        await workspace.api.delete(OWNER, f"{workspace.base}/integrations/{integration_id}")
    ).status_code == 204

    # Saving a new version that still points at the deleted integration is refused...
    again = await workspace.api.post(
        DEV,
        f"{base}/versions",
        json={"config": agent_config(tools=[grant(integration_id=integration_id)])},
    )
    assert await error_code(again) == "integration_not_found"

    # ...while a rollback only re-points the agent at a version exactly as it was saved. The tool
    # checks its integration every time it runs, so a dead one fails clearly then (see the engine
    # tests) instead of silently working.
    rollback = await workspace.api.post(DEV, f"{base}/rollback", json={"version": 1})
    assert rollback.status_code == 200
    (tool,) = rollback.json()["current_version"]["tools"]
    assert tool["config"] == {"integration_id": integration_id}


# ---------- the Slack tool ----------


async def test_the_catalog_lists_the_slack_tool(workspace: Workspace) -> None:
    tools = {t["key"]: t for t in (await workspace.api.get(DEV, "/api/v1/tools")).json()}
    slack = tools["slack.send_message"]
    assert slack["provider"] == "slack" and slack["is_sensitive"] is True
    schema = slack["input_schema"]
    Draft202012Validator.check_schema(schema)
    assert schema["required"] == ["channel", "text"]
    assert schema["properties"]["text"]["maxLength"] == 3000
    reduced = to_gemini_schema(schema)
    assert reduced["type"] == "OBJECT" and _all_types_are_text(reduced)
    assert set(reduced["properties"]) == {"channel", "text"}


async def test_an_agent_can_be_given_the_slack_tool_with_a_slack_integration(
    workspace: Workspace,
) -> None:
    slack_id = await integration(workspace, SLACK)
    response = await save(workspace, grant("slack.send_message", integration_id=slack_id))
    assert response.status_code == 201, response.text
    (tool,) = response.json()["current_version"]["tools"]
    assert (
        tool["provider"] == "slack" and tool["requires_approval"] is True
    )  # cannot be switched off


async def test_the_slack_tool_needs_a_slack_integration(workspace: Workspace) -> None:
    http_id = await integration(workspace, HTTP)
    wrong = await save(workspace, grant("slack.send_message", integration_id=http_id))
    assert await error_code(wrong) == "integration_wrong_type"
    missing = await save(workspace, grant("slack.send_message"))
    assert await error_code(missing) == "integration_required"


async def test_each_tool_must_use_an_integration_of_its_own_type(workspace: Workspace) -> None:
    http_id = await integration(workspace, HTTP)
    slack_id = await integration(workspace, SLACK)
    both = await save(
        workspace,
        grant("http.get", integration_id=http_id),
        grant("slack.send_message", integration_id=slack_id),
    )
    assert both.status_code == 201
    swapped = await save(
        workspace,
        grant("http.get", integration_id=slack_id),
        grant("slack.send_message", integration_id=http_id),
        name="Swapped",
    )
    assert swapped.status_code == 422
