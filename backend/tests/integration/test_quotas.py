"""Organization limits, daily quotas and usage (Phase 5B).

A run is checked against the organization's limits and reserves its share in one transaction, under
a lock, so simultaneous starts cannot exceed them. These tests drive the real API and database,
including real concurrent requests.
"""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.core.config import get_settings
from app.engine.executor import execute_run
from app.engine.llm import LLMClient, get_llm_client
from app.engine.provider_limiter import LimitedLLM, ProviderLimiter
from app.models.enums import LLMProvider
from tests.fakes import ScriptedLLM, call_tools, reply
from tests.integration.approval_helpers import CALC, Maker, decide, one_sum, resume, waiting
from tests.integration.engine_helpers import (
    ADMIN,
    DEV,
    MEMBER,
    OWNER,
    STRANGER,
    Queue,
    Workspace,
)
from tests.integration.seed import seed_org, seed_tool

PRICES = '{"gemini-test-model": {"input_per_mtok": "2", "output_per_mtok": "10"}}'


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue) -> None:
    """A (fake) model key and a recorder instead of Celery for every test here."""


@pytest.fixture
def prices(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MODEL_PRICES", PRICES)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def set_limits(ws: Workspace, who: str = OWNER, **values: Any) -> None:
    body = {"max_concurrent_runs": 1000, "daily_token_quota": 2_000_000_000, **values}
    response = await ws.api.put(who, f"{ws.base}/limits", json=body)
    assert response.status_code == 200, response.text


async def agent_with(ws: Workspace, **limits: Any) -> str:
    name = f"Agent {uuid.uuid4().hex[:8]}"  # names are unique within an organization
    return await ws.create_agent(name=name, tools=[], limits=limits)


def code_of(response: Any) -> str:
    return str(response.json()["error"]["code"])


async def finish(ws: Workspace, maker: Maker, run_id: str, llm: LLMClient | None = None) -> None:
    llm = llm or ScriptedLLM(reply("Done."))
    await execute_run(uuid.UUID(run_id), uuid.UUID(ws.org_id), maker=maker, llm=llm)


# ---------- reading and changing the limits ----------


async def test_an_organization_starts_with_the_platform_defaults(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORG_DEFAULT_MAX_CONCURRENT_RUNS", "7")
    monkeypatch.setenv("ORG_DEFAULT_DAILY_TOKEN_QUOTA", "123456")
    get_settings.cache_clear()
    response = await workspace.api.get(OWNER, f"{workspace.base}/limits")
    assert response.status_code == 200
    assert response.json() == {
        "max_concurrent_runs": 7,
        "daily_token_quota": 123_456,
        "daily_cost_quota_usd": None,
        "customized": False,
        "updated_at": None,
    }


async def test_the_documented_platform_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORG_DEFAULT_MAX_CONCURRENT_RUNS")
    monkeypatch.delenv("ORG_DEFAULT_DAILY_TOKEN_QUOTA")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.org_default_max_concurrent_runs == 5
    assert settings.org_default_daily_token_quota == 500_000
    assert settings.org_default_daily_cost_quota_usd is None


async def test_owners_and_admins_change_limits_and_it_is_audited(workspace: Workspace) -> None:
    for who, runs in ((OWNER, 3), (ADMIN, 4)):
        response = await workspace.api.put(
            who,
            f"{workspace.base}/limits",
            json={
                "max_concurrent_runs": runs,
                "daily_token_quota": 250_000,
                "daily_cost_quota_usd": "2.5",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["max_concurrent_runs"] == runs and body["customized"] is True
        assert body["daily_token_quota"] == 250_000 and body["daily_cost_quota_usd"] == 2.5
        assert body["updated_at"] is not None
    entries = workspace.api.scalar(
        "SELECT count(*) FROM audit_logs WHERE org_id = :o AND action = 'org.limits_updated'",
        o=workspace.org_id,
    )
    assert entries == 2
    assert workspace.api.scalar("SELECT count(*) FROM org_limits") == 1  # updated, not duplicated


async def test_developers_can_read_limits_but_not_change_them(workspace: Workspace) -> None:
    assert (await workspace.api.get(DEV, f"{workspace.base}/limits")).status_code == 200
    body = {"max_concurrent_runs": 2, "daily_token_quota": 10_000}
    assert (await workspace.api.put(DEV, f"{workspace.base}/limits", json=body)).status_code == 403
    assert (await workspace.api.delete(DEV, f"{workspace.base}/limits")).status_code == 403


async def test_members_and_strangers_cannot_see_limits(workspace: Workspace) -> None:
    for who in (MEMBER, STRANGER):
        for method in ("get", "put", "delete"):
            response = await getattr(workspace.api, method)(who, f"{workspace.base}/limits")
            assert response.status_code in (403, 404), (who, method)
    assert (await workspace.api.get(MEMBER, f"{workspace.base}/usage")).status_code == 403


@pytest.mark.parametrize(
    "bad",
    [
        {"max_concurrent_runs": 0, "daily_token_quota": 10_000},
        {"max_concurrent_runs": 1001, "daily_token_quota": 10_000},
        {"max_concurrent_runs": 5, "daily_token_quota": 999},
        {"max_concurrent_runs": 5, "daily_token_quota": 2_000_000_001},
        {"max_concurrent_runs": 5, "daily_token_quota": 10_000, "daily_cost_quota_usd": 0},
        {"max_concurrent_runs": 5, "daily_token_quota": 10_000, "daily_cost_quota_usd": -1},
        {"max_concurrent_runs": 5, "daily_token_quota": 10_000, "unknown": 1},
        {"max_concurrent_runs": 5},
    ],
)
async def test_nonsense_limits_are_refused(workspace: Workspace, bad: dict[str, Any]) -> None:
    response = await workspace.api.put(OWNER, f"{workspace.base}/limits", json=bad)
    assert response.status_code == 422
    assert workspace.api.scalar("SELECT count(*) FROM org_limits") == 0


async def test_limits_can_be_reset_to_the_defaults(workspace: Workspace) -> None:
    await set_limits(workspace, max_concurrent_runs=2)
    assert (await workspace.api.delete(OWNER, f"{workspace.base}/limits")).status_code == 204
    body = (await workspace.api.get(OWNER, f"{workspace.base}/limits")).json()
    assert body["customized"] is False and body["max_concurrent_runs"] == 1000
    # Resetting when nothing was customized is harmless and writes nothing to the audit log.
    assert (await workspace.api.delete(OWNER, f"{workspace.base}/limits")).status_code == 204
    resets = workspace.api.scalar(
        "SELECT count(*) FROM audit_logs WHERE action = 'org.limits_reset' AND org_id = :o",
        o=workspace.org_id,
    )
    assert resets == 1


# ---------- concurrency ----------


async def test_runs_beyond_the_concurrency_limit_are_refused_with_a_clear_message(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    await set_limits(workspace, max_concurrent_runs=2)
    agent = await agent_with(workspace)
    first = await workspace.new_run(agent)
    await workspace.new_run(agent)
    refused = await workspace.start_run(agent)
    assert refused.status_code == 429 and code_of(refused) == "concurrency_limit_reached"
    message = refused.json()["error"]["message"]
    assert "2 runs queued or running" in message and "limit is 2" in message
    assert workspace.api.scalar("SELECT count(*) FROM agent_runs") == 2  # nothing half-created

    await finish(workspace, runtime_maker, first)  # a slot frees up as soon as a run ends
    assert (await workspace.start_run(agent)).status_code == 201


async def test_a_run_waiting_for_a_person_does_not_hold_a_worker_slot(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    await set_limits(workspace, max_concurrent_runs=1)
    agent = await workspace.create_agent(tools=[CALC])
    run_id = await workspace.new_run(agent)
    await finish(workspace, runtime_maker, run_id, one_sum())
    assert (await workspace.detail(run_id))["status"] == "awaiting_approval"
    assert (await workspace.start_run(agent)).status_code == 201


async def test_simultaneous_starts_cannot_exceed_the_limit(workspace: Workspace) -> None:
    """Twelve requests at once against a limit of five: exactly five get in."""
    await set_limits(workspace, max_concurrent_runs=5)
    agent = await agent_with(workspace)
    responses = await asyncio.gather(*(workspace.start_run(agent) for _ in range(12)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [201] * 5 + [429] * 7, codes
    assert {code_of(r) for r in responses if r.status_code == 429} == {"concurrency_limit_reached"}
    assert workspace.api.scalar("SELECT count(*) FROM agent_runs") == 5


async def test_an_organizations_runs_never_count_against_another(
    workspace: Workspace,
) -> None:
    with workspace.api.owner.begin() as conn:
        seed_org(conn, "rival", seed_tool(conn))  # another organization with a queued run
    await set_limits(workspace, max_concurrent_runs=1)
    assert (await workspace.start_run(await agent_with(workspace))).status_code == 201


async def test_a_repeated_idempotent_request_is_not_refused_at_the_limit(
    workspace: Workspace,
) -> None:
    await set_limits(workspace, max_concurrent_runs=1)
    agent = await agent_with(workspace)
    headers = {"Idempotency-Key": "once"}
    first = await workspace.start_run(agent, headers=headers)
    assert first.status_code == 201
    again = await workspace.start_run(agent, headers=headers)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert (await workspace.start_run(agent)).status_code == 429  # a new request is refused


# ---------- daily token quota ----------


async def test_the_daily_quota_counts_what_open_runs_have_reserved(workspace: Workspace) -> None:
    await set_limits(workspace, daily_token_quota=100_000)
    agent = await agent_with(workspace, max_total_tokens=40_000)
    assert (await workspace.start_run(agent)).status_code == 201  # reserves 40,000
    assert (await workspace.start_run(agent)).status_code == 201  # 80,000
    refused = await workspace.start_run(agent)  # 120,000 would not fit
    assert refused.status_code == 429 and code_of(refused) == "daily_quota_reached"
    assert "midnight UTC" in refused.json()["error"]["message"]
    assert 1 <= int(refused.headers["retry-after"]) <= 86_400
    reserved = workspace.api.scalar("SELECT sum(reserved_tokens) FROM agent_runs")
    assert reserved == 80_000


async def test_a_finished_run_gives_back_what_it_did_not_use(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    await set_limits(workspace, daily_token_quota=100_000)
    agent = await agent_with(workspace, max_total_tokens=40_000)
    first = await workspace.new_run(agent)
    await workspace.new_run(agent)
    assert (await workspace.start_run(agent)).status_code == 429

    await finish(
        workspace, runtime_maker, first, ScriptedLLM(reply("Hi", tokens_in=600, tokens_out=400))
    )
    # 1,000 used + 40,000 still reserved by the other run + 40,000 for the new one.
    assert (await workspace.start_run(agent)).status_code == 201


async def test_tokens_already_spent_are_not_counted_twice(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    """A run that has spent 30,000 of its 40,000 holds 10,000 more, not another 40,000."""
    await set_limits(workspace, daily_token_quota=100_000)
    llm = ScriptedLLM(
        call_tools(
            ("utility_calculate", {"expression": "1+1"}), tokens_in=20_000, tokens_out=10_000
        )
    )
    agent = await workspace.create_agent(
        name="Spender", tools=[CALC], limits={"max_total_tokens": 40_000}
    )
    run_id = await workspace.new_run(agent)
    await finish(workspace, runtime_maker, run_id, llm)
    assert (await workspace.detail(run_id))["status"] == "awaiting_approval"

    today = (await workspace.api.get(OWNER, f"{workspace.base}/usage")).json()["today"]
    assert today["input_tokens"] + today["output_tokens"] == 30_000
    assert today["reserved_tokens"] == 10_000

    other = await agent_with(workspace, max_total_tokens=40_000)
    # 30,000 spent + 10,000 held + 40,000 = 80,000: fits. Counting the spent tokens twice
    # (30,000 + 40,000 + 40,000 = 110,000) would have refused it.
    assert (await workspace.start_run(other)).status_code == 201
    assert (await workspace.start_run(other)).status_code == 429  # 120,000 would not


async def test_an_agent_too_big_for_the_whole_quota_is_told_so(workspace: Workspace) -> None:
    await set_limits(workspace, daily_token_quota=20_000)
    refused = await workspace.start_run(await agent_with(workspace, max_total_tokens=50_000))
    assert refused.status_code == 409 and code_of(refused) == "run_exceeds_daily_quota"
    assert "50,000" in refused.json()["error"]["message"]
    assert "retry-after" not in refused.headers  # waiting would not help


async def test_the_run_remembers_what_it_reserved(workspace: Workspace) -> None:
    agent = await agent_with(workspace, max_total_tokens=12_345)
    run_id = await workspace.new_run(agent)
    row = workspace.api.scalar("SELECT reserved_tokens FROM agent_runs WHERE id = :r", r=run_id)
    assert row == 12_345


# ---------- reservations are released however a run ends ----------


async def _one_slot(ws: Workspace) -> str:
    """Limits that fit exactly one 40,000-token run; returns an agent that needs approval."""
    await set_limits(ws, daily_token_quota=50_000, max_concurrent_runs=1000)
    return await ws.create_agent(tools=[CALC], limits={"max_total_tokens": 40_000})


async def test_cancelling_releases_the_reservation(workspace: Workspace) -> None:
    agent = await _one_slot(workspace)
    run_id = await workspace.new_run(agent)
    assert (await workspace.start_run(agent)).status_code == 429
    await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    assert (await workspace.start_run(agent)).status_code == 201


async def test_a_failed_run_releases_the_reservation(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent = await _one_slot(workspace)
    run_id = await workspace.new_run(agent)
    await finish(workspace, runtime_maker, run_id, ScriptedLLM())  # the model call fails
    assert (await workspace.detail(run_id))["status"] == "failed"
    assert (await workspace.start_run(agent)).status_code == 201


async def test_a_rejected_approval_releases_the_reservation(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent = await _one_slot(workspace)
    llm = one_sum()
    run_id = await workspace.new_run(agent)
    await finish(workspace, runtime_maker, run_id, llm)
    assert (await workspace.start_run(agent)).status_code == 429  # it still holds its share
    await decide(workspace, (await waiting(workspace, run_id))["id"], "reject")
    await resume(workspace, runtime_maker, llm, run_id)
    assert (await workspace.detail(run_id))["status"] == "succeeded"
    assert (await workspace.start_run(agent)).status_code == 201


async def test_an_expired_approval_releases_the_reservation(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent = await _one_slot(workspace)
    run_id = await workspace.new_run(agent)
    await finish(workspace, runtime_maker, run_id, one_sum())
    approval = await waiting(workspace, run_id)
    workspace.api.execute(
        "UPDATE approvals SET expires_at = now() - interval '1 minute' WHERE id = :a",
        a=approval["id"],
    )
    assert (await workspace.detail(run_id))["status"] == "failed"
    assert (await workspace.start_run(agent)).status_code == 201


# ---------- daily cost quota ----------


async def test_a_cost_quota_needs_a_price_or_a_budget(workspace: Workspace) -> None:
    await set_limits(workspace, daily_cost_quota_usd="1")
    refused = await workspace.start_run(await agent_with(workspace))  # no budget, unpriced model
    assert refused.status_code == 409 and code_of(refused) == "cost_quota_needs_price"
    with_budget = await agent_with(workspace, cost_budget_usd=0.4)
    assert (await workspace.start_run(with_budget)).status_code == 201


async def test_a_cost_budget_is_reserved_against_the_cost_quota(workspace: Workspace) -> None:
    await set_limits(workspace, daily_cost_quota_usd="1")
    agent = await agent_with(workspace, cost_budget_usd=0.4)
    assert (await workspace.start_run(agent)).status_code == 201
    assert (await workspace.start_run(agent)).status_code == 201
    refused = await workspace.start_run(agent)  # 1.2 would not fit in 1.0
    assert refused.status_code == 429 and "cost quota" in refused.json()["error"]["message"]


async def test_without_a_budget_the_worst_case_price_is_reserved(
    workspace: Workspace, prices: None
) -> None:
    # 50,000 tokens at the dearest rate (10 USD per million) is at most 0.50 USD.
    await set_limits(workspace, daily_cost_quota_usd="1")
    agent = await agent_with(workspace)  # the default 50,000-token limit, no budget
    assert (await workspace.start_run(agent)).status_code == 201
    assert (await workspace.start_run(agent)).status_code == 201
    assert (await workspace.start_run(agent)).status_code == 429
    reserved = workspace.api.scalar("SELECT sum(reserved_cost_usd) FROM agent_runs")
    assert float(reserved) == pytest.approx(1.0)


async def test_an_agent_dearer_than_the_whole_cost_quota_is_told_so(workspace: Workspace) -> None:
    await set_limits(workspace, daily_cost_quota_usd="0.1")
    refused = await workspace.start_run(await agent_with(workspace, cost_budget_usd=0.5))
    assert refused.status_code == 409 and code_of(refused) == "run_exceeds_daily_quota"


# ---------- usage ----------


async def test_usage_of_a_quiet_organization_is_empty_but_complete(workspace: Workspace) -> None:
    body = (await workspace.api.get(OWNER, f"{workspace.base}/usage")).json()
    assert len(body["days"]) == 30
    assert all(d["runs"] == 0 and d["input_tokens"] == 0 for d in body["days"])
    assert body["by_agent"] == []
    today = body["today"]
    assert (today["input_tokens"], today["output_tokens"], today["cost_usd"]) == (0, 0, 0)
    assert today["busy_runs"] == 0 and today["reserved_tokens"] == 0
    assert body["limits"]["customized"] is False
    assert body["days"][-1]["day"] <= today["resets_at"][:10]


async def test_usage_reports_what_runs_really_used(
    workspace: Workspace, runtime_maker: Maker, prices: None
) -> None:
    agent = await workspace.create_agent(name="Counter", tools=[])
    run_id = await workspace.new_run(agent)
    await finish(
        workspace, runtime_maker, run_id, ScriptedLLM(reply("Hi", tokens_in=1000, tokens_out=500))
    )
    await workspace.new_run(agent)  # one more, still queued

    body = (await workspace.api.get(DEV, f"{workspace.base}/usage?days=7")).json()
    assert len(body["days"]) == 7
    today = body["days"][-1]
    assert today["runs"] == 2 and (today["input_tokens"], today["output_tokens"]) == (1000, 500)
    assert today["cost_usd"] == pytest.approx(0.007)  # 1000 * 2 + 500 * 10 micro-dollars
    assert body["today"]["busy_runs"] == 1  # the queued one
    assert body["by_agent"] == [
        {
            "agent_id": agent,
            "agent_name": "Counter",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cost_usd": pytest.approx(0.007),
        }
    ]


async def test_usage_asks_for_a_sensible_range(workspace: Workspace) -> None:
    for days in (0, 91, -3):
        response = await workspace.api.get(OWNER, f"{workspace.base}/usage?days={days}")
        assert response.status_code == 422, days
    assert (await workspace.api.get(OWNER, f"{workspace.base}/usage?days=90")).status_code == 200


# ---------- provider limits, seen from a run ----------


async def test_a_run_fails_clearly_when_the_provider_stays_busy(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    gate = ProviderLimiter(
        get_settings().redis_url,
        max_concurrent={"gemini": 1},
        per_minute={},
        wait_seconds=0.3,
        lease_seconds=30,
        prefix=f"test-run-{uuid.uuid4().hex[:8]}",
    )
    run_id = await workspace.new_run(await agent_with(workspace))
    async with gate.slot("gemini"):  # some other run is using the only slot
        await finish(
            workspace, runtime_maker, run_id, LimitedLLM(ScriptedLLM(reply("Hi")), "gemini", gate)
        )
    run = await workspace.detail(run_id)
    assert run["status"] == "failed" and "busy with other runs" in run["error"]
    # The model was never called, and the failure is recorded on the model-call step.
    assert [s["status"] for s in run["steps"]] == ["failed"]


async def test_the_real_gemini_client_is_wrapped_in_the_limiter() -> None:
    client = get_llm_client(LLMProvider.GEMINI)
    assert isinstance(client, LimitedLLM)
