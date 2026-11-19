"""The Slack tool with the real vault and database, and the engine's argument-preparation step.

The Slack tool is sensitive, so inside a run it is skipped until approvals exist (step 4D). These
tests therefore call the handler directly with the real integration lookup, and separately check
that a run never sends anything.
"""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.tools as tool_registry
from app.core.config import get_settings
from app.core.vault import generate_key
from app.engine.executor import execute_run
from app.tools import get_handler
from app.tools import slack as slack_tools
from app.tools.base import ToolContext, ToolError
from app.tools.integration_access import DatabaseIntegrationAccess
from tests.fakes import ScriptedLLM, call_tools, reply
from tests.integration.engine_helpers import ADMIN, Queue, Workspace
from tests.tls_server import LocalHttpsServer, Reply, local_fetcher

Maker = async_sessionmaker[AsyncSession]

TOKEN = "xoxb-4444-5555-DB-SECRET-bot-token"
CHANNEL = "C0123456789"
ENDPOINT = "/api/chat.postMessage"


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue, vault_key: str) -> None:
    """A (fake) model key, a recorder instead of Celery, and a vault key for every test."""


@pytest.fixture
async def server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[LocalHttpsServer]:
    local = LocalHttpsServer(tmp_path)
    await local.start()
    local.on(ENDPOINT, Reply(body=json.dumps({"ok": True, "ts": "1700000000.000100"})))
    monkeypatch.setattr(slack_tools, "new_fetcher", lambda: local_fetcher(local))
    yield local
    await local.stop()


async def make_integration(
    ws: Workspace,
    *,
    provider: str = "slack",
    config: dict[str, Any] | None = None,
    secret: str | None = TOKEN,
    name: str = "Team Slack",
) -> str:
    settings = config if config is not None else {"allowed_channels": [CHANNEL]}
    response = await ws.api.post(
        ADMIN,
        f"{ws.base}/integrations",
        json={"provider": provider, "name": name, "config": settings},
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


async def call(maker: Maker, ws: Workspace, integration_id: str, text: str = "Hello") -> Any:
    """Run the Slack handler the way the worker would: real lookup, real decryption."""
    handler = get_handler("slack.send_message")
    assert handler is not None
    context = ToolContext(
        org_id=uuid.UUID(ws.org_id),
        agent_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        integrations=DatabaseIntegrationAccess(maker, uuid.UUID(ws.org_id)),
        tool_config={"integration_id": integration_id},
    )
    return await handler({"channel": CHANNEL, "text": text}, context)


# ---------- the handler with the real integration ----------


async def test_the_saved_token_is_decrypted_and_used(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    integration_id = await make_integration(workspace)
    result = await call(runtime_maker, workspace, integration_id, "Deploy finished")
    assert result["ok"] is True
    (seen,) = server.seen
    assert seen.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(seen.body)["text"] == "Deploy finished"
    assert TOKEN not in json.dumps(result)


async def test_editing_the_allowed_channels_applies_at_once(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    integration_id = await make_integration(workspace)
    await workspace.api.patch(
        ADMIN,
        f"{workspace.base}/integrations/{integration_id}",
        json={"config": {"allowed_channels": ["C0999999999"]}},
    )
    with pytest.raises(ToolError, match="not allowed by this integration"):
        await call(runtime_maker, workspace, integration_id)
    assert server.seen == []


async def test_a_disabled_or_deleted_integration_sends_nothing(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    integration_id = await make_integration(workspace)
    base = f"{workspace.base}/integrations/{integration_id}"
    await workspace.api.patch(ADMIN, base, json={"status": "disabled"})
    with pytest.raises(ToolError, match="is disabled"):
        await call(runtime_maker, workspace, integration_id)
    await workspace.api.delete(ADMIN, base)
    with pytest.raises(ToolError, match="no longer exists"):
        await call(runtime_maker, workspace, integration_id)
    assert server.seen == []


async def test_an_http_integration_cannot_be_used_for_slack(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    http_id = await make_integration(
        workspace,
        provider="http",
        config={"allowed_hosts": ["api.example.com"]},
        name="Weather API",
    )
    with pytest.raises(ToolError, match="not the right type"):
        await call(runtime_maker, workspace, http_id)
    assert server.seen == []


async def test_an_integration_without_a_token_sends_nothing(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    integration_id = await make_integration(workspace, secret=None)
    with pytest.raises(ToolError, match="no bot token yet"):
        await call(runtime_maker, workspace, integration_id)
    assert server.seen == []


async def test_a_changed_server_key_is_an_unusable_token_and_leaks_nothing(
    workspace: Workspace,
    runtime_maker: Maker,
    server: LocalHttpsServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration_id = await make_integration(workspace)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", generate_key())
    get_settings.cache_clear()
    with pytest.raises(ToolError, match="could not be used") as caught:
        await call(runtime_maker, workspace, integration_id)
    assert TOKEN not in str(caught.value) and server.seen == []


async def test_another_organizations_integration_cannot_be_used(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    theirs = await workspace.api.post(
        "stranger@other.example.com",
        f"/api/v1/organizations/{workspace.other_org_id}/integrations",
        json={"provider": "slack", "name": "Theirs", "config": {"allowed_channels": [CHANNEL]}},
    )
    with pytest.raises(ToolError, match="no longer exists"):
        await call(runtime_maker, workspace, theirs.json()["id"])
    assert server.seen == []


# ---------- inside a run ----------


async def run_agent(
    ws: Workspace, maker: Maker, llm: ScriptedLLM, tools: list[dict[str, Any]]
) -> dict[str, Any]:
    agent_id = await ws.create_agent(tools=tools)
    run_id = await ws.new_run(agent_id, "Tell the team")
    await execute_run(uuid.UUID(run_id), uuid.UUID(ws.org_id), maker=maker, llm=llm)
    return await ws.detail(run_id)


def tool_step(run: dict[str, Any]) -> dict[str, Any]:
    (step,) = [s for s in run["steps"] if s["step_type"] == "tool_call"]
    found: dict[str, Any] = step
    return found


async def test_in_a_run_the_slack_tool_waits_for_approval_and_sends_nothing(
    workspace: Workspace, runtime_maker: Maker, server: LocalHttpsServer
) -> None:
    """Posting always needs a person; until approvals exist (4D) the request is skipped."""
    integration_id = await make_integration(workspace)
    llm = ScriptedLLM(
        call_tools(("slack_send_message", {"channel": CHANNEL, "text": "@channel hello"})),
        reply("I could not post it."),
    )
    run = await run_agent(
        workspace,
        runtime_maker,
        llm,
        [{"tool_key": "slack.send_message", "config": {"integration_id": integration_id}}],
    )
    step = tool_step(run)
    assert step["status"] == "skipped" and "approval" in step["error"]
    assert server.seen == []
    assert TOKEN not in json.dumps(run) and TOKEN not in json.dumps(llm.requests, default=str)


# ---------- the engine prepares arguments before a tool runs ----------


async def calculator_run(
    ws: Workspace, maker: Maker, expression: str
) -> tuple[dict[str, Any], ScriptedLLM]:
    llm = ScriptedLLM(call_tools(("utility_calculate", {"expression": expression})), reply("ok"))
    run = await run_agent(ws, maker, llm, [{"tool_key": "utility.calculate"}])
    return run, llm


async def test_prepared_arguments_are_what_the_handler_receives(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        tool_registry._PREPARERS, "utility.calculate", lambda arguments: {"expression": "2 + 2"}
    )
    run, _ = await calculator_run(workspace, runtime_maker, "1 + 1")
    step = tool_step(run)
    assert step["input"] == {"expression": "1 + 1"}  # what the model asked for is kept as asked
    assert step["output"]["result"] == 4  # but the prepared form is what ran


async def test_a_preparer_can_refuse_and_the_tool_does_not_run(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(arguments: dict[str, Any]) -> dict[str, Any]:
        raise ToolError("Not allowed in this test.")

    monkeypatch.setitem(tool_registry._PREPARERS, "utility.calculate", refuse)
    run, llm = await calculator_run(workspace, runtime_maker, "1 + 1")
    step = tool_step(run)
    assert step["status"] == "failed" and step["error"] == "Not allowed in this test."
    assert llm.requests[1]["messages"][-1]["results"][0]["is_error"] is True


async def test_tools_without_a_preparer_behave_exactly_as_before(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run, _ = await calculator_run(workspace, runtime_maker, "2 + 3 * 4")
    assert tool_step(run)["output"] == {"expression": "2 + 3 * 4", "result": 14}
