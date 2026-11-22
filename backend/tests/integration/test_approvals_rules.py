"""The rules around approvals: who may decide, races, the clock, cancellation and crashes.

The promise under test: an action runs at most once, only after a person approved exactly what it
would do, and every way of getting that wrong (double clicks, late clicks, a dead worker, a
cancelled run) ends in a clear message and never in a second or unapproved action.
"""

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

import app.tools as tool_registry
from app.core.config import get_settings
from app.db.tenancy import use_tenant
from app.engine.executor import execute_run
from app.repositories import runs as run_repo
from tests.fakes import ScriptedLLM, call_tools, reply
from tests.integration.approval_helpers import (
    CALC,
    Maker,
    audit_actions,
    decide,
    one_sum,
    resume,
    start,
    tool_steps,
    waiting,
)
from tests.integration.engine_helpers import ADMIN, DEV, MEMBER, OWNER, STRANGER, Queue, Workspace


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue) -> None:
    """A (fake) model key and a recorder instead of Celery for every test here."""


def approval_status(ws: Workspace, approval_id: str) -> str:
    return str(ws.api.scalar("SELECT status FROM approvals WHERE id = :a", a=approval_id))


# ---------- who can do what ----------


@pytest.mark.parametrize("who", [OWNER, ADMIN])
async def test_owners_and_admins_can_decide(
    workspace: Workspace, runtime_maker: Maker, queue: Queue, who: str
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id, who=who)
    response = await decide(workspace, approval["id"], who=who)
    assert response.status_code == 200 and response.json()["decided_by_name"] == who
    assert len(queue.resumes) == 1


async def test_developers_can_see_approvals_but_not_decide(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id, who=DEV)  # may list...
    one = await workspace.api.get(DEV, f"{workspace.base}/approvals/{approval['id']}")
    assert one.status_code == 200 and one.json()["proposed_input"] == {"expression": "1 + 1"}
    for action in ("approve", "reject"):  # ...but not decide
        refused = await decide(workspace, approval["id"], action, who=DEV)
        assert refused.status_code == 403
    assert approval_status(workspace, approval["id"]) == "pending" and queue.resumes == []


async def test_members_see_nothing(workspace: Workspace, runtime_maker: Maker) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    api, base = workspace.api, workspace.base
    assert (await api.get(MEMBER, f"{base}/approvals")).status_code == 403
    assert (await api.get(MEMBER, f"{base}/approvals/{approval['id']}")).status_code == 403
    assert (await decide(workspace, approval["id"], who=MEMBER)).status_code == 403
    assert approval_status(workspace, approval["id"]) == "pending"


async def test_another_organization_cannot_see_or_decide(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    theirs = f"/api/v1/organizations/{workspace.other_org_id}/approvals"
    api = workspace.api
    assert (await api.get(STRANGER, theirs)).json()["items"] == []
    assert (await api.get(STRANGER, f"{theirs}/{approval['id']}")).status_code == 404
    for action in ("approve", "reject"):
        denied = await api.post(STRANGER, f"{theirs}/{approval['id']}/{action}")
        assert denied.status_code == 404
    assert approval_status(workspace, approval["id"]) == "pending" and queue.resumes == []


async def test_an_unknown_approval_is_not_found(workspace: Workspace) -> None:
    missing = str(uuid.uuid4())
    assert (
        await workspace.api.get(OWNER, f"{workspace.base}/approvals/{missing}")
    ).status_code == 404
    assert (await decide(workspace, missing)).status_code == 404


# ---------- the decision body ----------


async def test_the_note_is_optional_trimmed_and_limited(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    for bad in ({"note": "x" * 501}, {"extra": 1}, {"note": 5}):
        refused = await workspace.api.post(
            OWNER, f"{workspace.base}/approvals/{approval['id']}/approve", json=bad
        )
        assert refused.status_code == 422
    assert approval_status(workspace, approval["id"]) == "pending"
    ok = await decide(workspace, approval["id"], note="  fine  ")
    assert ok.json()["decision_note"] == "fine"


async def test_a_blank_note_is_stored_as_no_note(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    ok = await workspace.api.post(
        OWNER, f"{workspace.base}/approvals/{approval['id']}/approve", json={"note": "   "}
    )
    assert ok.status_code == 200 and ok.json()["decision_note"] is None


# ---------- deciding twice, and at the same time ----------


async def test_a_second_click_hands_the_run_over_again_then_is_refused(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    assert (await decide(workspace, approval["id"])).status_code == 200
    # The run has not been picked up yet, so the same decision again is a safe retry.
    again = await decide(workspace, approval["id"], who=ADMIN)
    assert (
        again.status_code == 200 and again.json()["decided_by_name"] == OWNER
    )  # first decider kept
    assert len(queue.resumes) == 2

    await resume(workspace, runtime_maker, llm, run_id)
    await resume(workspace, runtime_maker, llm, run_id)  # the duplicate task from the retry
    late = await decide(workspace, approval["id"])
    assert late.status_code == 409 and late.json()["error"]["code"] == "approval_already_decided"
    assert f"approved by {OWNER}" in late.json()["error"]["message"]
    run = await workspace.detail(run_id)
    assert run["status"] == "succeeded" and llm.calls == 2
    assert [s["status"] for s in tool_steps(run)] == ["succeeded"]  # the action ran once


async def test_the_opposite_decision_after_deciding_is_refused(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"], "approve")
    flip = await decide(workspace, approval["id"], "reject", who=ADMIN)
    assert flip.status_code == 409 and flip.json()["error"]["code"] == "approval_already_decided"
    assert approval_status(workspace, approval["id"]) == "approved"


async def test_two_people_deciding_at_once_get_exactly_one_decision(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    first, second = await asyncio.gather(
        decide(workspace, approval["id"], "approve", who=OWNER),
        decide(workspace, approval["id"], "reject", who=ADMIN),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    assert approval_status(workspace, approval["id"]) in ("approved", "rejected")
    assert (
        workspace.api.scalar(
            "SELECT count(*) FROM audit_logs WHERE action IN ('approval.approved','approval.rejected')"
        )
        == 1
    )
    assert len(queue.resumes) == 1


async def test_resuming_twice_never_runs_the_action_twice(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"])
    await asyncio.gather(
        resume(workspace, runtime_maker, llm, run_id),
        resume(workspace, runtime_maker, llm, run_id),
        resume(workspace, runtime_maker, llm, run_id),
    )
    run = await workspace.detail(run_id)
    assert run["status"] == "succeeded" and llm.calls == 2
    assert [s["status"] for s in tool_steps(run)] == ["succeeded"]
    assert len([s for s in run["steps"] if s["step_type"] == "llm_call"]) == 2


async def test_resuming_before_anyone_decided_does_nothing(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    await resume(workspace, runtime_maker, llm, run_id)
    run = await workspace.detail(run_id)
    assert run["status"] == "awaiting_approval" and llm.calls == 1
    assert (await waiting(workspace, run_id))["status"] == "pending"


async def test_a_late_duplicate_resume_does_not_disturb_a_newer_wait(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = ScriptedLLM(
        call_tools(
            ("utility_calculate", {"expression": "1 + 1"}),
            ("utility_calculate", {"expression": "2 + 2"}),
        ),
        reply("done"),
    )
    run_id = await start(workspace, runtime_maker, llm)
    first = await waiting(workspace, run_id)
    await decide(workspace, first["id"])
    await resume(workspace, runtime_maker, llm, run_id)  # runs the first, pauses on the second
    second = await waiting(workspace, run_id)
    await resume(workspace, runtime_maker, llm, run_id)  # a stale duplicate of the first resume
    run = await workspace.detail(run_id)
    assert run["status"] == "awaiting_approval"
    assert (await waiting(workspace, run_id))["id"] == second["id"]
    assert [s["status"] for s in tool_steps(run)] == ["succeeded", "awaiting_approval"]


async def test_a_run_waits_on_one_decision_at_a_time(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    with pytest.raises(IntegrityError):
        workspace.api.execute(
            "INSERT INTO approvals (id, org_id, run_id, tool_key, proposed_input, status) "
            "SELECT gen_random_uuid(), org_id, run_id, tool_key, '{}'::jsonb, 'pending' "
            "FROM approvals WHERE run_id = :r",
            r=run_id,
        )


# ---------- the clock ----------


def make_overdue(ws: Workspace, approval_id: str) -> None:
    ws.api.execute(
        "UPDATE approvals SET expires_at = now() - interval '1 minute' WHERE id = :a", a=approval_id
    )


@pytest.mark.parametrize("looking_at", ["approval", "approvals", "run", "runs"])
async def test_an_approval_nobody_decides_in_time_expires_and_stops_its_run(
    workspace: Workspace, runtime_maker: Maker, looking_at: str
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    make_overdue(workspace, approval["id"])

    base = workspace.base  # merely looking is enough: each of these keeps the clock honest
    path = {
        "approval": f"{base}/approvals/{approval['id']}",
        "approvals": f"{base}/approvals",
        "run": f"{base}/runs/{run_id}",
        "runs": f"{base}/runs",
    }[looking_at]
    assert (await workspace.api.get(OWNER, path)).status_code == 200

    assert approval_status(workspace, approval["id"]) == "expired"
    run = await workspace.detail(run_id)
    assert run["status"] == "failed" and "expired" in run["error"]
    assert run["finished_at"] is not None and run["pending_approval"] is None
    assert [s["status"] for s in tool_steps(run)] == ["skipped"]
    assert "Nobody decided in time" in tool_steps(run)[0]["error"]
    assert workspace.api.scalar("SELECT checkpoint IS NULL FROM agent_runs WHERE id = :r", r=run_id)
    assert audit_actions(workspace) == ["approval.requested", "approval.expired"]
    assert llm.calls == 1  # the action never ran, and the model was never asked again


async def test_deciding_after_expiry_is_refused_and_resuming_does_nothing(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    make_overdue(workspace, approval["id"])
    for action in ("approve", "reject"):
        late = await decide(workspace, approval["id"], action)
        assert late.status_code == 409 and late.json()["error"]["code"] == "approval_expired"
    assert queue.resumes == []
    await resume(workspace, runtime_maker, llm, run_id)  # a stray task changes nothing
    assert (await workspace.detail(run_id))["status"] == "failed" and llm.calls == 1


async def test_an_approval_expiring_between_looking_and_clicking_is_refused(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    make_overdue(workspace, approval["id"])  # the deciding call itself notices
    assert (await decide(workspace, approval["id"])).status_code == 409
    assert approval_status(workspace, approval["id"]) == "expired" and queue.resumes == []


async def test_the_expiry_time_is_configurable(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPROVAL_EXPIRY_HOURS", "1")
    get_settings.cache_clear()
    try:
        run_id = await start(workspace, runtime_maker, one_sum())
        assert 3_500 < (await waiting(workspace, run_id))["seconds_left"] <= 3_600
    finally:
        get_settings.cache_clear()


async def test_waiting_time_is_not_work_time(workspace: Workspace, runtime_maker: Maker) -> None:
    """A run that waited two days is not mistaken for one whose worker died."""
    run_id = await start(workspace, runtime_maker, one_sum())
    workspace.api.execute(
        "UPDATE agent_runs SET started_at = now() - interval '2 days' WHERE id = :r", r=run_id
    )
    assert (await workspace.detail(run_id))["status"] == "awaiting_approval"  # not reaped

    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"])
    await claim(workspace, runtime_maker, run_id)  # a worker has just picked it up
    assert (await workspace.detail(run_id))["status"] == "running"  # measured from the resume

    workspace.api.execute(
        "UPDATE agent_runs SET last_resumed_at = now() - interval '2 days' WHERE id = :r", r=run_id
    )
    assert (await workspace.detail(run_id))["status"] == "failed"  # now genuinely stale


async def claim(ws: Workspace, maker: Maker, run_id: str) -> None:
    """What a worker does first when it resumes a run: take it, once."""
    async with maker() as session:
        await use_tenant(session, org_id=uuid.UUID(ws.org_id))
        taken = await run_repo.claim_for_resume(session, uuid.UUID(ws.org_id), uuid.UUID(run_id))
        await session.commit()
    assert taken is not None


# ---------- cancelling ----------


async def test_cancelling_a_waiting_run_withdraws_the_request(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)

    cancelled = await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    assert cancelled.status_code == 200

    assert approval_status(workspace, approval["id"]) == "cancelled"
    run = await workspace.detail(run_id)
    assert run["status"] == "cancelled" and run["pending_approval"] is None
    assert [s["status"] for s in tool_steps(run)] == ["skipped"]
    assert workspace.api.scalar("SELECT checkpoint IS NULL FROM agent_runs WHERE id = :r", r=run_id)
    assert audit_actions(workspace) == ["approval.requested", "approval.cancelled"]
    late = await decide(workspace, approval["id"])
    assert late.status_code == 409 and late.json()["error"]["code"] == "approval_cancelled"
    assert queue.resumes == [] and llm.calls == 1


async def test_cancelling_after_approval_but_before_the_resume_runs_nothing(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"])
    await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    await resume(workspace, runtime_maker, llm, run_id)
    run = await workspace.detail(run_id)
    assert run["status"] == "cancelled" and llm.calls == 1
    assert [s["status"] for s in tool_steps(run)] == ["skipped"]  # the approved action did not run


async def test_a_run_cancelled_while_the_action_was_being_proposed_asks_nobody(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent_id = await workspace.create_agent(tools=[CALC])
    run_id = await workspace.new_run(agent_id)

    async def cancelled_mid_call() -> Any:
        workspace.api.execute(
            "UPDATE agent_runs SET status = 'cancelled', finished_at = now() WHERE id = :r",
            r=run_id,
        )
        return call_tools(("utility_calculate", {"expression": "1 + 1"}))

    llm = ScriptedLLM(cancelled_mid_call)
    await execute_run(uuid.UUID(run_id), uuid.UUID(workspace.org_id), maker=runtime_maker, llm=llm)
    run = await workspace.detail(run_id)
    assert run["status"] == "cancelled"
    assert workspace.api.scalar("SELECT count(*) FROM approvals WHERE status = 'pending'") == 0
    assert [s["status"] for s in tool_steps(run)] == ["skipped"]


# ---------- a worker dying mid-way ----------


async def test_a_worker_dying_during_an_approved_action_is_reported_never_retried(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    step_id = tool_steps(await workspace.detail(run_id))[0]["id"]
    await decide(workspace, approval["id"])

    # A worker takes the run, marks the action started... and is killed.
    await claim(workspace, runtime_maker, run_id)
    workspace.api.execute("UPDATE run_steps SET status = 'running' WHERE id = :s", s=step_id)
    workspace.api.execute(
        "UPDATE agent_runs SET last_resumed_at = now() - interval '1 hour' WHERE id = :r", r=run_id
    )

    run = await workspace.detail(run_id)  # the orphan check closes it
    assert run["status"] == "failed"
    assert "unknown whether the action happened" in run["error"]
    (step,) = tool_steps(run)
    assert step["status"] == "failed" and "unknown whether the action happened" in step["error"]

    await resume(workspace, runtime_maker, llm, run_id)  # the redelivered task
    assert llm.calls == 1 and (await workspace.detail(run_id))["status"] == "failed"
    assert [s["status"] for s in tool_steps(await workspace.detail(run_id))] == ["failed"]


async def test_a_worker_dying_before_the_action_started_says_so(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"])
    await claim(workspace, runtime_maker, run_id)  # claimed, but the action never started
    workspace.api.execute(
        "UPDATE agent_runs SET last_resumed_at = now() - interval '1 hour' WHERE id = :r", r=run_id
    )
    run = await workspace.detail(run_id)
    assert run["status"] == "failed" and "unknown" not in run["error"]
    (step,) = tool_steps(run)
    assert step["status"] == "skipped" and "was not run" in step["error"]


async def test_an_unreadable_saved_state_fails_the_run_instead_of_guessing(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"])
    workspace.api.execute(
        "UPDATE agent_runs SET checkpoint = jsonb_set(checkpoint, '{version}', '99') WHERE id = :r",
        r=run_id,
    )
    await resume(workspace, runtime_maker, llm, run_id)
    run = await workspace.detail(run_id)
    assert run["status"] == "failed" and "saved state" in run["error"]
    assert llm.calls == 1 and tool_steps(run)[0]["status"] != "succeeded"


# ---------- what runs is what was approved ----------


async def test_an_action_that_changed_since_approval_is_not_run(
    workspace: Workspace, runtime_maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"])
    # A deploy changes how arguments are prepared between the approval and the resume.
    monkeypatch.setitem(
        tool_registry._PREPARERS, "utility.calculate", lambda arguments: {"expression": "9 + 9"}
    )
    await resume(workspace, runtime_maker, llm, run_id)
    run = await workspace.detail(run_id)
    (step,) = tool_steps(run)
    assert step["status"] == "failed" and "no longer matches what was approved" in step["error"]
    assert step["output"] is None
    assert llm.requests[1]["messages"][-1]["results"][0]["is_error"] is True


# ---------- the queue can fail ----------


async def test_a_failed_hand_over_is_saved_and_can_be_retried(
    workspace: Workspace, runtime_maker: Maker, queue: Queue
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)

    queue.fail_resume = True
    failed = await decide(workspace, approval["id"])
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "queue_unavailable"
    assert "Press the button again" in failed.json()["error"]["message"]
    assert approval_status(workspace, approval["id"]) == "approved"  # the decision is kept
    assert (await workspace.detail(run_id))["status"] == "awaiting_approval"

    queue.fail_resume = False
    retried = await decide(workspace, approval["id"])
    assert retried.status_code == 200 and len(queue.resumes) == 1
    await resume(workspace, runtime_maker, llm, run_id)
    assert (await workspace.detail(run_id))["status"] == "succeeded"


# ---------- the inbox ----------


async def test_the_inbox_filters_pages_and_shows_newest_first(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    runs = [await start(workspace, runtime_maker, one_sum(), name=f"Helper {n}") for n in range(3)]
    approvals = [await waiting(workspace, run_id) for run_id in runs]
    await decide(workspace, approvals[0]["id"], "approve")
    await decide(workspace, approvals[1]["id"], "reject")
    api, base = workspace.api, f"{workspace.base}/approvals"

    everything = (await api.get(OWNER, base)).json()
    assert everything["total"] == 3
    assert [item["id"] for item in everything["items"]] == [a["id"] for a in reversed(approvals)]

    def ids(page: dict[str, Any]) -> set[str]:
        return {item["id"] for item in page["items"]}

    assert ids((await api.get(OWNER, base, params={"status": "pending"})).json()) == {
        approvals[2]["id"]
    }
    assert ids((await api.get(OWNER, base, params={"status": "approved"})).json()) == {
        approvals[0]["id"]
    }
    assert ids((await api.get(OWNER, base, params={"status": "rejected"})).json()) == {
        approvals[1]["id"]
    }
    assert (await api.get(OWNER, base, params={"status": "expired"})).json()["total"] == 0
    assert ids((await api.get(OWNER, base, params={"run_id": runs[1]})).json()) == {
        approvals[1]["id"]
    }
    page = (await api.get(OWNER, base, params={"limit": 2, "offset": 2})).json()
    assert (len(page["items"]), page["total"]) == (1, 3)
    assert (await api.get(OWNER, base, params={"status": "nonsense"})).status_code == 422
    assert (await api.get(OWNER, base, params={"limit": 0})).status_code == 422


async def test_a_decided_approval_keeps_the_exact_record(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"], note="ok", who=ADMIN)
    kept = (await workspace.api.get(OWNER, f"{workspace.base}/approvals/{approval['id']}")).json()
    assert kept["status"] == "approved" and kept["seconds_left"] is None
    assert kept["proposed_input"] == {"expression": "1 + 1"}
    assert kept["decided_by_name"] == ADMIN and kept["decision_note"] == "ok"
    assert json.dumps(kept).count("1 + 1") == 1
