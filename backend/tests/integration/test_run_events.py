"""The run event log and its live stream (Phase 5A).

Events are written in the same transaction as the change they describe, numbered gap-free per run,
carry no step data, and can be replayed from any sequence number. The stream is checked against
the real API, engine and database.
"""

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.core.config import get_settings
from app.db.tenancy import use_tenant
from app.engine.executor import execute_run
from app.models.enums import RunEventType
from app.repositories import run_events
from app.schemas.run import RunEventRead
from app.services.run_events import frame, parse_last_event_id
from tests.fakes import ScriptedLLM, reply
from tests.integration.approval_helpers import (
    CALC,
    Maker,
    decide,
    one_sum,
    resume,
    start,
    waiting,
)
from tests.integration.engine_helpers import DEV, MEMBER, OWNER, STRANGER, Queue, Workspace

CALC_NO_APPROVAL = {"tool_key": "utility.calculate"}
ALLOWED_DATA_KEYS = {
    "status",
    "decision",
    "approval_id",
    "step_id",
    "sequence",
    "step_type",
    "tool_key",
}


@pytest.fixture(autouse=True)
def _ai_configured(gemini_key: None, queue: Queue) -> None:
    """A (fake) model key and a recorder instead of Celery for every test here."""


@pytest.fixture
def fast_stream(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Poll quickly so streams react within a blink."""
    monkeypatch.setenv("RUN_STREAM_POLL_SECONDS", "0.05")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def set_stream(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in values.items():
        monkeypatch.setenv(f"RUN_STREAM_{name.upper()}_SECONDS", value)
    get_settings.cache_clear()


async def events_of(
    ws: Workspace, run_id: str, who: str = OWNER, **params: Any
) -> list[dict[str, Any]]:
    response = await ws.api.get(who, f"{ws.base}/runs/{run_id}/events", params=params)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


def types_of(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


def parse_sse(body: str) -> list[dict[str, Any]]:
    frames = []
    for block in body.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        frames.append(
            {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}
        )
    return frames


def stream_path(ws: Workspace, run_id: str) -> str:
    return f"{ws.base}/runs/{run_id}/events/stream"


# ---------- what gets recorded ----------


async def test_a_plain_run_records_its_story_in_order(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, ScriptedLLM(reply("Hello!")), tools=[])
    events = await events_of(workspace, run_id)
    assert types_of(events) == [
        "run.queued",
        "run.started",
        "step.started",
        "step.finished",
        "run.finished",
    ]
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]  # gap-free, from 1
    assert events[2]["data"]["step_type"] == "llm_call"
    assert events[3]["data"]["status"] == "succeeded"
    assert events[-1]["data"] == {"status": "succeeded"}
    assert workspace.api.scalar("SELECT event_seq FROM agent_runs WHERE id = :r", r=run_id) == 5


async def test_a_tool_run_records_each_step(workspace: Workspace, runtime_maker: Maker) -> None:
    run_id = await start(workspace, runtime_maker, one_sum(), tools=[CALC_NO_APPROVAL])
    events = await events_of(workspace, run_id)
    assert types_of(events) == [
        "run.queued",
        "run.started",
        "step.started",  # model call 1
        "step.finished",
        "step.started",  # the tool
        "step.finished",
        "step.started",  # model call 2
        "step.finished",
        "run.finished",
    ]
    assert events[4]["data"]["tool_key"] == "utility.calculate"
    assert [e["seq"] for e in events] == list(range(1, 10))


async def test_a_failed_run_says_so(workspace: Workspace, runtime_maker: Maker) -> None:
    llm = ScriptedLLM()  # nothing scripted: the model call blows up
    run_id = await start(workspace, runtime_maker, llm, tools=[])
    events = await events_of(workspace, run_id)
    assert events[-1]["type"] == "run.finished" and events[-1]["data"] == {"status": "failed"}


async def test_an_approved_run_records_the_whole_approval_round_trip(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    waiting_events = await events_of(workspace, run_id)
    assert types_of(waiting_events) == [
        "run.queued",
        "run.started",
        "step.started",
        "step.finished",
        "step.started",  # the tool, waiting
        "approval.requested",
        "run.awaiting_approval",
    ]
    approval = await waiting(workspace, run_id)
    assert waiting_events[5]["data"]["approval_id"] == approval["id"]
    assert waiting_events[6]["data"] == {"approval_id": approval["id"]}

    assert (await decide(workspace, approval["id"], "approve")).status_code == 200
    await resume(workspace, runtime_maker, llm, run_id)
    events = await events_of(workspace, run_id)
    assert types_of(events)[7:] == [
        "approval.decided",
        "run.resumed",
        "step.finished",  # the approved action ran
        "step.started",  # model call 2
        "step.finished",
        "run.finished",
    ]
    assert events[7]["data"] == {"approval_id": approval["id"], "decision": "approved"}
    assert events[8]["data"] == {"decision": "approved"}
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


async def test_a_rejected_run_records_the_rejection(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    llm = one_sum()
    run_id = await start(workspace, runtime_maker, llm)
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"], "reject")
    await resume(workspace, runtime_maker, llm, run_id)
    events = await events_of(workspace, run_id)
    decided = [e for e in events if e["type"] == "approval.decided"]
    assert [e["data"]["decision"] for e in decided] == ["rejected"]
    assert events[-1]["type"] == "run.finished"


async def test_cancelling_a_queued_run_ends_its_story(workspace: Workspace) -> None:
    agent_id = await workspace.create_agent(tools=[])
    run_id = await workspace.new_run(agent_id)
    assert (
        await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    ).status_code == 200
    assert types_of(await events_of(workspace, run_id)) == ["run.queued", "run.cancelled"]


async def test_cancelling_a_waiting_run_withdraws_the_approval_in_the_log(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    events = await events_of(workspace, run_id)
    assert types_of(events)[-2:] == ["approval.decided", "run.cancelled"]
    assert events[-2]["data"]["decision"] == "cancelled"


async def test_an_expired_approval_is_recorded_and_stops_the_run(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, one_sum())
    approval = await waiting(workspace, run_id)
    workspace.api.execute(
        "UPDATE approvals SET expires_at = now() - interval '1 minute' WHERE id = :a",
        a=approval["id"],
    )
    await workspace.detail(run_id)  # merely looking keeps the clock honest
    events = await events_of(workspace, run_id)
    assert types_of(events)[-2:] == ["approval.decided", "run.finished"]
    assert events[-2]["data"]["decision"] == "expired"
    assert events[-1]["data"] == {"status": "failed"}


async def test_a_run_that_could_not_be_queued_says_so(workspace: Workspace, queue: Queue) -> None:
    agent_id = await workspace.create_agent(tools=[])
    queue.fail = True
    assert (await workspace.start_run(agent_id)).status_code == 503
    run_id = str(workspace.api.scalar("SELECT id FROM agent_runs WHERE agent_id = :a", a=agent_id))
    events = await events_of(workspace, run_id)
    assert types_of(events) == ["run.queued", "run.finished"]
    assert events[-1]["data"] == {"status": "failed"}


async def test_a_repeated_idempotent_request_adds_no_events(workspace: Workspace) -> None:
    agent_id = await workspace.create_agent(tools=[])
    headers = {"Idempotency-Key": "same-key"}
    first = await workspace.start_run(agent_id, headers=headers)
    again = await workspace.start_run(agent_id, headers=headers)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert types_of(await events_of(workspace, first.json()["id"])) == ["run.queued"]


async def test_events_never_carry_what_a_step_handled(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    secret = "SECRET-MARKER-4471"
    llm = one_sum(f"I will add {secret}")
    run_id = await start(
        workspace, runtime_maker, llm, tools=[CALC], message=f"Please keep {secret} private"
    )
    approval = await waiting(workspace, run_id)
    await decide(workspace, approval["id"], "approve")
    await resume(workspace, runtime_maker, llm, run_id)
    raw = workspace.api.scalar(
        "SELECT string_agg(data::text, ' ') FROM run_events WHERE run_id = :r", r=run_id
    )
    assert secret not in str(raw) and "1 + 1" not in str(raw)
    for event in await events_of(workspace, run_id):
        assert set(event["data"]) <= ALLOWED_DATA_KEYS, event


async def test_two_writers_never_take_the_same_number(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent_id = await workspace.create_agent(tools=[])
    run_id = uuid.UUID(await workspace.new_run(agent_id))  # event 1 is run.queued

    async def write(index: int) -> int | None:
        async with runtime_maker() as session:
            await use_tenant(session, org_id=uuid.UUID(workspace.org_id))
            seq = await run_events.emit(
                session, run_id, RunEventType.STEP_STARTED, {"sequence": index}
            )
            await session.commit()
            return seq

    taken = await asyncio.gather(*(write(i) for i in range(25)))
    assert sorted(t for t in taken if t is not None) == list(range(2, 27))
    stored = workspace.api.scalar(
        "SELECT array_agg(seq ORDER BY seq) FROM run_events WHERE run_id = :r", r=str(run_id)
    )
    assert list(stored) == list(range(1, 27))


async def test_an_event_for_a_run_of_another_organization_writes_nothing(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    agent_id = await workspace.create_agent(tools=[])
    run_id = uuid.UUID(await workspace.new_run(agent_id))
    async with runtime_maker() as session:
        await use_tenant(session, org_id=uuid.UUID(workspace.other_org_id))
        assert await run_events.emit(session, run_id, RunEventType.CANCELLED) is None
        await session.commit()
    assert types_of(await events_of(workspace, str(run_id))) == ["run.queued"]
    assert (
        workspace.api.scalar("SELECT event_seq FROM agent_runs WHERE id = :r", r=str(run_id)) == 1
    )


# ---------- reading ----------


async def test_events_can_be_paged_with_after_and_limit(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, ScriptedLLM(reply("Hi")), tools=[])
    assert [e["seq"] for e in await events_of(workspace, run_id, after=2)] == [3, 4, 5]
    assert [e["seq"] for e in await events_of(workspace, run_id, limit=2)] == [1, 2]
    assert await events_of(workspace, run_id, after=5) == []
    assert (
        await workspace.api.get(OWNER, f"{workspace.base}/runs/{run_id}/events?limit=0")
    ).status_code == 422
    assert (
        await workspace.api.get(OWNER, f"{workspace.base}/runs/{run_id}/events?after=-1")
    ).status_code == 422


async def test_every_member_can_read_events_but_strangers_cannot(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, ScriptedLLM(reply("Hi")), tools=[])
    assert len(await events_of(workspace, run_id, who=MEMBER)) == 5
    for path in ("events", "events/stream"):
        stranger = await workspace.api.get(STRANGER, f"{workspace.base}/runs/{run_id}/{path}")
        assert stranger.status_code in (403, 404), path


async def test_events_of_an_unknown_run_are_not_found(workspace: Workspace) -> None:
    missing = uuid.uuid4()
    for path in ("events", "events/stream"):
        response = await workspace.api.get(OWNER, f"{workspace.base}/runs/{missing}/{path}")
        assert response.status_code == 404 and response.json()["error"]["code"] == "run_not_found"


async def test_events_are_unreadable_without_signing_in(workspace: Workspace) -> None:
    agent_id = await workspace.create_agent(tools=[])
    run_id = await workspace.new_run(agent_id)
    for path in ("events", "events/stream"):
        response = await workspace.api.client.get(f"{workspace.base}/runs/{run_id}/{path}")
        assert response.status_code == 401


async def test_deleting_an_organization_takes_its_event_log_with_it(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, ScriptedLLM(reply("Hi")), tools=[])
    assert workspace.api.scalar("SELECT count(*) FROM run_events WHERE run_id = :r", r=run_id) == 5
    assert (await workspace.api.delete(OWNER, workspace.base)).status_code == 204
    assert workspace.api.scalar("SELECT count(*) FROM run_events WHERE run_id = :r", r=run_id) == 0


# ---------- the stream ----------


async def test_the_stream_replays_a_finished_run_and_ends(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, ScriptedLLM(reply("Hi")), tools=[])
    response = await workspace.api.get(OWNER, stream_path(workspace, run_id))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    frames = parse_sse(response.text)
    assert [f["id"] for f in frames] == [1, 2, 3, 4, 5]
    assert [f["event"] for f in frames] == types_of(await events_of(workspace, run_id))
    assert frames[-1]["data"]["type"] == "run.finished"
    assert frames[-1]["data"]["data"] == {"status": "succeeded"}


async def test_a_reconnecting_client_receives_only_what_it_missed(
    workspace: Workspace, runtime_maker: Maker
) -> None:
    run_id = await start(workspace, runtime_maker, ScriptedLLM(reply("Hi")), tools=[])
    path = stream_path(workspace, run_id)
    by_query = parse_sse((await workspace.api.get(OWNER, path, params={"after": 3})).text)
    assert [f["id"] for f in by_query] == [4, 5]
    by_header = parse_sse(
        (await workspace.api.get(OWNER, path, headers={"Last-Event-ID": "3"})).text
    )
    assert [f["id"] for f in by_header] == [4, 5]
    for junk in ("abc", "-4", ""):  # unusable values mean "from the start", never an error
        everything = parse_sse(
            (await workspace.api.get(OWNER, path, headers={"Last-Event-ID": junk})).text
        )
        assert [f["id"] for f in everything] == [1, 2, 3, 4, 5], junk
    assert parse_sse((await workspace.api.get(OWNER, path, params={"after": 5})).text) == []


async def test_a_stream_opened_early_delivers_everything_as_it_happens(
    workspace: Workspace, runtime_maker: Maker, fast_stream: None
) -> None:
    agent_id = await workspace.create_agent(tools=[])
    run_id = await workspace.new_run(agent_id)  # queued; nobody has started it yet
    watcher = asyncio.create_task(workspace.api.get(OWNER, stream_path(workspace, run_id)))
    await asyncio.sleep(0.3)
    assert not watcher.done()  # still watching a run that has not finished

    await execute_run(
        uuid.UUID(run_id),
        uuid.UUID(workspace.org_id),
        maker=runtime_maker,
        llm=ScriptedLLM(reply("Hi")),
    )
    response = await asyncio.wait_for(watcher, timeout=5)
    assert [f["event"] for f in parse_sse(response.text)] == [
        "run.queued",
        "run.started",
        "step.started",
        "step.finished",
        "run.finished",
    ]


async def test_a_stream_ends_when_a_run_is_cancelled(
    workspace: Workspace, fast_stream: None
) -> None:
    agent_id = await workspace.create_agent(tools=[])
    run_id = await workspace.new_run(agent_id)
    watcher = asyncio.create_task(workspace.api.get(OWNER, stream_path(workspace, run_id)))
    await asyncio.sleep(0.2)
    await workspace.api.post(DEV, f"{workspace.base}/runs/{run_id}/cancel")
    response = await asyncio.wait_for(watcher, timeout=5)
    assert [f["event"] for f in parse_sse(response.text)] == ["run.queued", "run.cancelled"]


async def test_a_stream_gives_up_after_its_time_limit_so_clients_reconnect(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_stream(monkeypatch, poll="0.05", max="0.4")
    agent_id = await workspace.create_agent(tools=[])
    run_id = await workspace.new_run(agent_id)  # never started, so never finishes
    response = await asyncio.wait_for(
        workspace.api.get(OWNER, stream_path(workspace, run_id)), timeout=5
    )
    assert [f["id"] for f in parse_sse(response.text)] == [1]


async def test_a_quiet_stream_sends_keep_alive_comments(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_stream(monkeypatch, poll="0.05", heartbeat="0.1", max="0.6")
    agent_id = await workspace.create_agent(tools=[])
    run_id = await workspace.new_run(agent_id)
    response = await asyncio.wait_for(
        workspace.api.get(OWNER, stream_path(workspace, run_id)), timeout=5
    )
    assert response.text.count(": keep-alive\n\n") >= 2


async def test_a_waiting_stream_holds_no_database_transaction(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stream must hand its connection back: held open for minutes it would drain the pool."""
    set_stream(monkeypatch, poll="0.6", max="1.5")
    agent_id = await workspace.create_agent(tools=[])
    run_id = await workspace.new_run(agent_id)
    watcher = asyncio.create_task(workspace.api.get(OWNER, stream_path(workspace, run_id)))
    await asyncio.sleep(0.4)  # the first poll is done; the next is 0.2 seconds away
    stuck = workspace.api.scalar(
        "SELECT count(*) FROM pg_stat_activity WHERE usename = 'agent_app' "
        "AND state = 'idle in transaction' AND now() - state_change > interval '150 milliseconds'"
    )
    await asyncio.wait_for(watcher, timeout=5)
    assert stuck == 0


# ---------- small pieces ----------


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, 0), ("", 0), ("7", 7), ("0", 0), ("-3", 0), ("abc", 0), ("1.5", 0)],
)
def test_last_event_id_is_read_leniently(header: str | None, expected: int) -> None:
    assert parse_last_event_id(header) == expected


def test_a_frame_carries_its_sequence_number_as_the_event_id() -> None:
    event = RunEventRead.model_validate(
        {
            "seq": 7,
            "type": RunEventType.FINISHED,
            "data": {"status": "succeeded"},
            "created_at": "2026-11-24T10:00:00Z",
        }
    )
    text = frame(event)
    assert text.startswith("id: 7\nevent: run.finished\ndata: ") and text.endswith("\n\n")
    payload = json.loads(text.split("data: ", 1)[1])
    assert payload["seq"] == 7 and payload["data"] == {"status": "succeeded"}
