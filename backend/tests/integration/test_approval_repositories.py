"""The database rules behind approvals, tested directly.

The API layers above these rules clean up expired and cancelled approvals before they act, so a
mistake in a rule could hide behind them. These tests call the rules themselves, with no clean-up
in front, to prove each one holds on its own: a decision succeeds only for a pending, unexpired
approval of a run that is waiting for it, and a run can be claimed for resuming only once.
"""

import uuid
from typing import Any

import pytest

from app.db.tenancy import use_tenant
from app.models.enums import ApprovalStatus
from app.repositories import approvals as approval_repo
from app.repositories import runs as run_repo
from tests.integration.approval_helpers import Maker, decide, one_sum, start, waiting
from tests.integration.engine_helpers import OWNER, Queue, Workspace


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue) -> None:
    """A (fake) model key and a recorder instead of Celery for every test here."""


async def waiting_approval(ws: Workspace, maker: Maker) -> tuple[str, str]:
    run_id = await start(ws, maker, one_sum())
    return run_id, (await waiting(ws, run_id))["id"]


async def try_decide(
    ws: Workspace,
    maker: Maker,
    approval_id: str,
    status: ApprovalStatus = ApprovalStatus.APPROVED,
) -> bool:
    """Record a decision straight through the repository, with no clean-up first."""
    user_id = ws.api.scalar("SELECT id FROM users WHERE email = :e", e=OWNER)
    async with maker() as session:
        await use_tenant(session, org_id=uuid.UUID(ws.org_id))
        done = await approval_repo.decide(
            session,
            uuid.UUID(ws.org_id),
            uuid.UUID(approval_id),
            status=status,
            user_id=uuid.UUID(str(user_id)),
            note=None,
        )
        await session.commit()
    return done


async def try_claim(ws: Workspace, maker: Maker, run_id: str) -> Any:
    async with maker() as session:
        await use_tenant(session, org_id=uuid.UUID(ws.org_id))
        claim = await run_repo.claim_for_resume(session, uuid.UUID(ws.org_id), uuid.UUID(run_id))
        await session.commit()
    return claim


def state_of(ws: Workspace, run_id: str) -> tuple[str, bool]:
    row = ws.api.scalar("SELECT status FROM agent_runs WHERE id = :r", r=run_id)
    has_checkpoint = ws.api.scalar(
        "SELECT checkpoint IS NOT NULL FROM agent_runs WHERE id = :r", r=run_id
    )
    return str(row), bool(has_checkpoint)


# ---------- deciding ----------


async def test_a_pending_approval_can_be_decided_exactly_once(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    _, approval_id = await waiting_approval(workspace, runtime_maker)
    assert await try_decide(workspace, runtime_maker, approval_id) is True
    assert await try_decide(workspace, runtime_maker, approval_id) is False  # same decision
    assert await try_decide(workspace, runtime_maker, approval_id, ApprovalStatus.REJECTED) is False
    assert (
        workspace.api.scalar("SELECT status FROM approvals WHERE id = :a", a=approval_id)
        == "approved"
    )


async def test_an_overdue_approval_cannot_be_decided_even_if_nobody_cleaned_it_up(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    _, approval_id = await waiting_approval(workspace, runtime_maker)
    workspace.api.execute(
        "UPDATE approvals SET expires_at = now() - interval '1 second' WHERE id = :a", a=approval_id
    )
    assert await try_decide(workspace, runtime_maker, approval_id) is False
    assert (
        workspace.api.scalar("SELECT status FROM approvals WHERE id = :a", a=approval_id)
        == "pending"
    )


@pytest.mark.parametrize("run_status", ["cancelled", "failed", "succeeded", "running"])
async def test_an_approval_cannot_be_decided_unless_its_run_is_waiting_for_it(
    workspace: Workspace, runtime_maker: Maker, run_status: str
) -> None:
    run_id, approval_id = await waiting_approval(workspace, runtime_maker)
    workspace.api.execute("UPDATE agent_runs SET status = :s WHERE id = :r", s=run_status, r=run_id)
    assert await try_decide(workspace, runtime_maker, approval_id) is False
    assert (
        workspace.api.scalar("SELECT status FROM approvals WHERE id = :a", a=approval_id)
        == "pending"
    )


@pytest.mark.parametrize("status", ["approved", "rejected", "expired", "cancelled"])
async def test_an_approval_that_is_no_longer_pending_stays_as_it_is(
    workspace: Workspace, runtime_maker: Maker, status: str
) -> None:
    _, approval_id = await waiting_approval(workspace, runtime_maker)
    workspace.api.execute("UPDATE approvals SET status = :s WHERE id = :a", s=status, a=approval_id)
    assert await try_decide(workspace, runtime_maker, approval_id) is False
    assert (
        workspace.api.scalar("SELECT status FROM approvals WHERE id = :a", a=approval_id) == status
    )


# ---------- claiming a run to resume it ----------


async def test_a_decided_run_can_be_claimed_once_and_only_once(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id, approval_id = await waiting_approval(workspace, runtime_maker)
    await decide(workspace, approval_id)

    first = await try_claim(workspace, runtime_maker, run_id)
    assert first is not None
    assert first.approval.status is ApprovalStatus.APPROVED
    assert first.checkpoint["awaiting"]["approval_id"] == approval_id
    assert state_of(workspace, run_id) == ("running", True)  # taken
    # The saved state is kept, now as progress noting which approval it answers, so a worker lost
    # right after claiming the run can be replaced and resume from the same decision.
    saved = workspace.api.scalar("SELECT checkpoint FROM agent_runs WHERE id = :r", r=run_id)
    assert saved["kind"] == "progress"
    assert saved["resume"] == {"awaiting": first.checkpoint["awaiting"]}
    assert workspace.api.scalar(
        "SELECT heartbeat_at IS NOT NULL FROM agent_runs WHERE id = :r", r=run_id
    )
    assert workspace.api.scalar(
        "SELECT last_resumed_at IS NOT NULL FROM agent_runs WHERE id = :r", r=run_id
    )

    assert await try_claim(workspace, runtime_maker, run_id) is None  # a second worker gets nothing


async def test_a_run_cannot_be_claimed_before_its_approval_is_decided(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id, _ = await waiting_approval(workspace, runtime_maker)
    assert await try_claim(workspace, runtime_maker, run_id) is None
    assert state_of(workspace, run_id) == ("awaiting_approval", True)  # left exactly as it was


@pytest.mark.parametrize("status", ["expired", "cancelled", "pending"])
async def test_a_run_cannot_be_claimed_for_an_approval_that_was_not_decided(
    workspace: Workspace, runtime_maker: Maker, status: str
) -> None:
    run_id, approval_id = await waiting_approval(workspace, runtime_maker)
    workspace.api.execute("UPDATE approvals SET status = :s WHERE id = :a", s=status, a=approval_id)
    assert await try_claim(workspace, runtime_maker, run_id) is None
    assert state_of(workspace, run_id) == ("awaiting_approval", True)


@pytest.mark.parametrize("run_status", ["running", "cancelled", "failed", "succeeded", "queued"])
async def test_only_a_waiting_run_can_be_claimed_even_if_a_checkpoint_is_still_there(
    workspace: Workspace, runtime_maker: Maker, run_status: str
) -> None:
    run_id, approval_id = await waiting_approval(workspace, runtime_maker)
    await decide(workspace, approval_id)
    workspace.api.execute("UPDATE agent_runs SET status = :s WHERE id = :r", s=run_status, r=run_id)
    assert await try_claim(workspace, runtime_maker, run_id) is None
    assert state_of(workspace, run_id) == (run_status, True)  # untouched


async def test_a_run_without_a_saved_state_cannot_be_claimed(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id, approval_id = await waiting_approval(workspace, runtime_maker)
    await decide(workspace, approval_id)
    workspace.api.execute("UPDATE agent_runs SET checkpoint = NULL WHERE id = :r", r=run_id)
    assert await try_claim(workspace, runtime_maker, run_id) is None


async def test_another_organizations_run_cannot_be_claimed(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id, approval_id = await waiting_approval(workspace, runtime_maker)
    await decide(workspace, approval_id)
    async with runtime_maker() as session:
        await use_tenant(session, org_id=uuid.UUID(workspace.other_org_id))
        claim = await run_repo.claim_for_resume(
            session, uuid.UUID(workspace.other_org_id), uuid.UUID(run_id)
        )
    assert claim is None
    assert state_of(workspace, run_id) == ("awaiting_approval", True)


# ---------- pausing ----------


async def test_only_a_running_run_can_be_paused(workspace: Workspace, runtime_maker: Maker) -> None:
    run_id, _ = await waiting_approval(workspace, runtime_maker)
    async with runtime_maker() as session:
        await use_tenant(session, org_id=uuid.UUID(workspace.org_id))
        # The run is already waiting, so pausing it again must not overwrite its saved state.
        assert (
            await run_repo.pause(session, uuid.UUID(run_id), {"version": 1, "x": "other"}) is False
        )
    saved = workspace.api.scalar("SELECT checkpoint->>'x' FROM agent_runs WHERE id = :r", r=run_id)
    assert saved is None  # the original state is intact
