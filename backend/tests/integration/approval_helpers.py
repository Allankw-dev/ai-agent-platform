"""Shared helpers for the approval tests: start a run, find its approval, decide it."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.engine.executor import execute_run, resume_run
from tests.fakes import ScriptedLLM, call_tools, reply
from tests.integration.engine_helpers import OWNER, Workspace

Maker = async_sessionmaker[AsyncSession]

CALC = {"tool_key": "utility.calculate", "requires_approval": True}
CLOCK = {"tool_key": "utility.current_time"}


async def start(
    ws: Workspace,
    maker: Maker,
    llm: ScriptedLLM,
    tools: list[dict[str, Any]] | None = None,
    message: str = "Add them up",
    name: str = "Helper",
) -> str:
    agent_id = await ws.create_agent(name=name, tools=tools if tools is not None else [CALC])
    run_id = await ws.new_run(agent_id, message)
    await execute_run(uuid.UUID(run_id), uuid.UUID(ws.org_id), maker=maker, llm=llm)
    return run_id


async def resume(ws: Workspace, maker: Maker, llm: ScriptedLLM, run_id: str) -> None:
    await resume_run(uuid.UUID(run_id), uuid.UUID(ws.org_id), maker=maker, llm=llm)


async def waiting(ws: Workspace, run_id: str, who: str = OWNER) -> dict[str, Any]:
    """The one pending approval of a run."""
    response = await ws.api.get(
        who, f"{ws.base}/approvals", params={"status": "pending", "run_id": run_id}
    )
    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    return dict(item)


async def decide(
    ws: Workspace,
    approval_id: str,
    action: str = "approve",
    who: str = OWNER,
    note: str | None = None,
) -> Any:
    return await ws.api.post(
        who, f"{ws.base}/approvals/{approval_id}/{action}", json={"note": note} if note else None
    )


def tool_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in run["steps"] if s["step_type"] == "tool_call"]


def llm_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in run["steps"] if s["step_type"] == "llm_call"]


def audit_actions(ws: Workspace) -> list[str]:
    rows = str(
        ws.api.scalar(
            "SELECT coalesce(string_agg(action, ',' ORDER BY created_at, id), '') FROM audit_logs "
            "WHERE action LIKE 'approval.%'"
        )
    )
    return [a for a in rows.split(",") if a]


def one_sum(text: str = "") -> ScriptedLLM:
    return ScriptedLLM(
        call_tools(("utility_calculate", {"expression": "1 + 1"}), text=text),
        reply("The answer is 2."),
    )
