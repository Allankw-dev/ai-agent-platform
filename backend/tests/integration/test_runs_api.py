"""Starting, listing, reading and cancelling runs through the real API (Celery is replaced)."""

import uuid
from typing import Any

import pytest

from app.core.config import get_settings
from tests.integration.engine_helpers import (
    ADMIN,
    DEV,
    MEMBER,
    OWNER,
    STRANGER,
    Queue,
    Workspace,
    agent_config,
)


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue) -> None:
    """Every test here runs with a (fake) key and with Celery replaced by a recorder."""


def code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# ---------- starting ----------


async def test_starting_a_run_queues_it_for_the_worker(workspace: Workspace, queue: Queue) -> None:
    agent_id = await workspace.create_agent()
    response = await workspace.start_run(agent_id, "Summarize my inbox")
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "queued"
    assert run["trigger"] == "manual"
    assert run["agent_id"] == agent_id
    assert run["agent_version"] == 1
    assert run["agent_name"] == "Helper"
    assert run["input"] == {"message": "Summarize my inbox"}
    assert (run["input_tokens"], run["output_tokens"], run["cost_usd"]) == (0, 0, 0)
    assert run["started_at"] is None and run["finished_at"] is None
    assert queue.calls == [(uuid.UUID(run["id"]), uuid.UUID(workspace.org_id))]


@pytest.mark.parametrize(
    ("who", "status"), [(OWNER, 201), (ADMIN, 201), (DEV, 201), (MEMBER, 403), (STRANGER, 404)]
)
async def test_who_can_start_runs(
    workspace: Workspace, queue: Queue, who: str, status: int
) -> None:
    agent_id = await workspace.create_agent()
    response = await workspace.start_run(agent_id, who=who)
    assert response.status_code == status
    assert len(queue.calls) == (1 if status == 201 else 0)


async def test_the_test_trigger_is_recorded(workspace: Workspace) -> None:
    agent_id = await workspace.create_agent()
    response = await workspace.start_run(agent_id, body={"trigger": "test"})
    assert response.json()["trigger"] == "test"


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 20_001},
        {},
        {"message": "hi", "trigger": "api"},
        {"message": "hi", "agent_version_id": str(uuid.uuid4())},
    ],
)
async def test_invalid_run_requests_are_rejected(
    workspace: Workspace, queue: Queue, body: dict[str, Any]
) -> None:
    agent_id = await workspace.create_agent()
    response = await workspace.api.post(DEV, f"{workspace.base}/agents/{agent_id}/runs", json=body)
    assert response.status_code == 422
    assert queue.calls == []


async def test_draft_and_active_agents_run_but_disabled_and_deleted_ones_do_not(
    workspace: Workspace, queue: Queue
) -> None:
    agent_id = await workspace.create_agent()  # a draft
    assert (await workspace.start_run(agent_id)).status_code == 201
    await workspace.api.patch(DEV, f"{workspace.base}/agents/{agent_id}", json={"status": "active"})
    assert (await workspace.start_run(agent_id)).status_code == 201

    await workspace.api.patch(
        DEV, f"{workspace.base}/agents/{agent_id}", json={"status": "disabled"}
    )
    blocked = await workspace.start_run(agent_id)
    assert blocked.status_code == 409 and code(blocked) == "agent_not_runnable"

    await workspace.api.delete(DEV, f"{workspace.base}/agents/{agent_id}")
    gone = await workspace.start_run(agent_id)
    assert gone.status_code == 404 and code(gone) == "agent_not_found"
    assert len(queue.calls) == 2


async def test_an_agent_from_another_organization_is_not_found(
    workspace: Workspace, queue: Queue
) -> None:
    agent_id = await workspace.create_agent()
    response = await workspace.api.post(
        STRANGER,
        f"/api/v1/organizations/{workspace.other_org_id}/agents/{agent_id}/runs",
        json={"message": "hi"},
    )
    assert response.status_code == 404
    assert queue.calls == []


async def test_runs_are_refused_up_front_when_the_provider_has_no_key(
    workspace: Workspace, queue: Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_id = await workspace.create_agent()
    monkeypatch.delenv("GEMINI_API_KEY")
    get_settings.cache_clear()
    response = await workspace.start_run(agent_id)
    assert response.status_code == 503 and code(response) == "ai_not_configured"
    assert queue.calls == []
    listing = await workspace.api.get(OWNER, f"{workspace.base}/runs")
    assert listing.json()["total"] == 0  # nothing half-created


async def test_a_run_uses_the_agent_version_current_at_that_moment(workspace: Workspace) -> None:
    agent_id = await workspace.create_agent()
    first = await workspace.new_run(agent_id)
    version = await workspace.api.post(
        DEV,
        f"{workspace.base}/agents/{agent_id}/versions",
        json={"config": agent_config(system_instructions="Changed.")},
    )
    assert version.status_code == 201
    second = await workspace.new_run(agent_id)
    assert (await workspace.detail(first))["agent_version"] == 1
    assert (await workspace.detail(second))["agent_version"] == 2


# ---------- idempotency ----------


async def test_the_same_idempotency_key_returns_the_same_run(
    workspace: Workspace, queue: Queue
) -> None:
    agent_id = await workspace.create_agent()
    headers = {"Idempotency-Key": "order-42"}
    first = await workspace.start_run(agent_id, headers=headers)
    again = await workspace.start_run(agent_id, headers=headers)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    assert len(queue.calls) == 1


async def test_an_idempotency_key_cannot_be_reused_for_another_agent(workspace: Workspace) -> None:
    one = await workspace.create_agent(name="One")
    two = await workspace.create_agent(name="Two")
    headers = {"Idempotency-Key": "shared"}
    assert (await workspace.start_run(one, headers=headers)).status_code == 201
    clash = await workspace.start_run(two, headers=headers)
    assert clash.status_code == 409 and code(clash) == "idempotency_key_reused"


async def test_idempotency_keys_are_per_organization(workspace: Workspace) -> None:
    agent_id = await workspace.create_agent()
    headers = {"Idempotency-Key": "same-everywhere"}
    mine = await workspace.start_run(agent_id, headers=headers)
    other_agent = await workspace.api.post(
        STRANGER,
        f"/api/v1/organizations/{workspace.other_org_id}/agents",
        json={"name": "Theirs", "config": agent_config()},
    )
    theirs = await workspace.api.post(
        STRANGER,
        f"/api/v1/organizations/{workspace.other_org_id}/agents/{other_agent.json()['id']}/runs",
        json={"message": "hi"},
        headers=headers,
    )
    assert mine.status_code == 201 and theirs.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"]


async def test_an_empty_idempotency_key_is_rejected(workspace: Workspace) -> None:
    agent_id = await workspace.create_agent()
    response = await workspace.start_run(agent_id, headers={"Idempotency-Key": ""})
    assert response.status_code == 422 and code(response) == "invalid_idempotency_key"


# ---------- when the queue is down ----------


async def test_a_failed_hand_off_fails_the_run_and_frees_the_key(
    workspace: Workspace, queue: Queue
) -> None:
    agent_id = await workspace.create_agent()
    headers = {"Idempotency-Key": "retry-me"}
    queue.fail = True
    down = await workspace.start_run(agent_id, headers=headers)
    assert down.status_code == 503 and code(down) == "queue_unavailable"

    runs = (await workspace.api.get(OWNER, f"{workspace.base}/runs")).json()
    assert runs["total"] == 1
    assert runs["items"][0]["status"] == "failed"
    assert runs["items"][0]["error"] == "The run could not be queued."

    queue.fail = False
    retry = await workspace.start_run(agent_id, headers=headers)  # the same key works again
    assert retry.status_code == 201
    assert retry.json()["id"] != runs["items"][0]["id"]


# ---------- reading ----------


async def test_listing_filtering_and_ordering_runs(workspace: Workspace) -> None:
    one = await workspace.create_agent(name="One")
    two = await workspace.create_agent(name="Two")
    first = await workspace.new_run(one)
    second = await workspace.new_run(two)
    third = await workspace.new_run(one)
    workspace.api.execute("UPDATE agent_runs SET status = 'failed' WHERE id = :r", r=first)

    everything = (await workspace.api.get(MEMBER, f"{workspace.base}/runs")).json()
    assert [r["id"] for r in everything["items"]] == [third, second, first]  # newest first
    assert everything["total"] == 3

    by_agent = (await workspace.api.get(MEMBER, f"{workspace.base}/runs?agent_id={one}")).json()
    assert {r["id"] for r in by_agent["items"]} == {first, third}
    by_status = (await workspace.api.get(MEMBER, f"{workspace.base}/runs?status=failed")).json()
    assert [r["id"] for r in by_status["items"]] == [first]

    page = (await workspace.api.get(MEMBER, f"{workspace.base}/runs?limit=1&offset=1")).json()
    assert [r["id"] for r in page["items"]] == [second]
    assert page["total"] == 3


async def test_a_bad_status_filter_is_rejected(workspace: Workspace) -> None:
    response = await workspace.api.get(OWNER, f"{workspace.base}/runs?status=exploded")
    assert response.status_code == 422


async def test_runs_are_invisible_to_other_organizations(workspace: Workspace) -> None:
    agent_id = await workspace.create_agent()
    run_id = await workspace.new_run(agent_id)

    # Not a member of this organization: the organization itself is not found.
    assert (await workspace.api.get(STRANGER, f"{workspace.base}/runs")).status_code == 404
    assert (await workspace.api.get(STRANGER, f"{workspace.base}/runs/{run_id}")).status_code == 404
    # Asking through their own organization: the run does not exist there.
    theirs = f"/api/v1/organizations/{workspace.other_org_id}/runs"
    assert (await workspace.api.get(STRANGER, theirs)).json()["total"] == 0
    assert (await workspace.api.get(STRANGER, f"{theirs}/{run_id}")).status_code == 404


async def test_an_unknown_run_is_not_found(workspace: Workspace) -> None:
    response = await workspace.api.get(OWNER, f"{workspace.base}/runs/{uuid.uuid4()}")
    assert response.status_code == 404 and code(response) == "run_not_found"


async def test_a_new_run_has_no_steps_yet(workspace: Workspace) -> None:
    run_id = await workspace.new_run(await workspace.create_agent())
    assert (await workspace.detail(run_id))["steps"] == []


# ---------- cancelling ----------


async def test_cancelling_a_queued_run(workspace: Workspace) -> None:
    run_id = await workspace.new_run(await workspace.create_agent())
    response = await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["finished_at"] is not None
    again = await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    assert again.status_code == 409 and code(again) == "run_not_cancellable"


async def test_a_finished_run_cannot_be_cancelled(workspace: Workspace) -> None:
    run_id = await workspace.new_run(await workspace.create_agent())
    workspace.api.execute("UPDATE agent_runs SET status = 'succeeded' WHERE id = :r", r=run_id)
    response = await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    assert response.status_code == 409
    assert (await workspace.detail(run_id))["status"] == "succeeded"


@pytest.mark.parametrize(("who", "status"), [(ADMIN, 200), (MEMBER, 403), (STRANGER, 404)])
async def test_who_can_cancel_runs(workspace: Workspace, who: str, status: int) -> None:
    run_id = await workspace.new_run(await workspace.create_agent())
    response = await workspace.api.post(who, f"{workspace.base}/runs/{run_id}/cancel")
    assert response.status_code == status


async def test_cancelling_an_unknown_run_is_not_found(workspace: Workspace) -> None:
    response = await workspace.api.post(DEV, f"{workspace.base}/runs/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


# ---------- audit ----------


async def test_starting_and_cancelling_are_audited(workspace: Workspace) -> None:
    run_id = await workspace.new_run(await workspace.create_agent())
    await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    actions = workspace.api.scalar(
        "SELECT string_agg(action, ',' ORDER BY action) FROM audit_logs "
        "WHERE action LIKE 'run.%' AND resource_id = :r",
        r=run_id,
    )
    assert actions == "run.cancelled,run.created"


async def test_runs_carry_the_agent_name_even_after_the_agent_is_deleted(
    workspace: Workspace,
) -> None:
    agent_id = await workspace.create_agent(name="Short-lived bot")
    run_id = await workspace.new_run(agent_id)
    await workspace.api.delete(DEV, f"{workspace.base}/agents/{agent_id}")

    listed = (await workspace.api.get(MEMBER, f"{workspace.base}/runs")).json()
    assert [r["agent_name"] for r in listed["items"]] == ["Short-lived bot"]
    assert (await workspace.detail(run_id))["agent_name"] == "Short-lived bot"
