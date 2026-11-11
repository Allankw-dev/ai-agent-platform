"""A small organization with agents and runs, driven through the real API."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from tests.integration.api_helpers import Api

OWNER = "owner@acme.example.com"
ADMIN = "admin@acme.example.com"
DEV = "dev@acme.example.com"
MEMBER = "member@acme.example.com"
STRANGER = "stranger@other.example.com"


def agent_config(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "provider": "gemini",
        "model": "gemini-test-model",
        "system_instructions": "You are a careful assistant.",
        "tools": [],
    }
    base.update(overrides)
    return base


@dataclass
class Queue:
    """Records (run_id, org_id) hand-offs instead of talking to Celery."""

    calls: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)
    fail: bool = False

    async def dispatch(self, run_id: uuid.UUID, org_id: uuid.UUID) -> None:
        if self.fail:
            raise RuntimeError("the broker is down")
        self.calls.append((run_id, org_id))


@dataclass
class Workspace:
    api: Api
    org_id: str
    other_org_id: str

    @property
    def base(self) -> str:
        return f"/api/v1/organizations/{self.org_id}"

    async def create_agent(
        self, who: str = DEV, name: str = "Helper", activate: bool = False, **cfg: Any
    ) -> str:
        body = {"name": name, "config": agent_config(**cfg)}
        response = await self.api.post(who, f"{self.base}/agents", json=body)
        assert response.status_code == 201, response.text
        agent_id = str(response.json()["id"])
        if activate:
            patch = await self.api.patch(
                who, f"{self.base}/agents/{agent_id}", json={"status": "active"}
            )
            assert patch.status_code == 200, patch.text
        return agent_id

    async def start_run(
        self,
        agent_id: str,
        message: str = "Hello",
        who: str = DEV,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        return await self.api.post(
            who,
            f"{self.base}/agents/{agent_id}/runs",
            json={"message": message, **(body or {})},
            headers=headers,
        )

    async def new_run(self, agent_id: str, message: str = "Hello") -> str:
        response = await self.start_run(agent_id, message)
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    async def detail(self, run_id: str, who: str = OWNER) -> dict[str, Any]:
        response = await self.api.get(who, f"{self.base}/runs/{run_id}")
        assert response.status_code == 200, response.text
        return dict(response.json())
