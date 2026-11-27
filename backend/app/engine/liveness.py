"""Proof that a worker is still alive and still holds its run.

While a run executes, its worker writes a heartbeat to the run row every few seconds (the database
is the authority: a run whose heartbeat has stopped has lost its worker) and lists the run in a
Redis sorted set. Row Level Security means no query can look across organizations, so the sorted
set is only how the scheduler *finds* candidates; it then asks the database about each one, inside
that organization. If Redis is unavailable nothing breaks: the set is simply not updated, and the
read-time cleanup in services/runs.py still closes runs whose worker is gone.
"""

import asyncio
import contextlib
import uuid

import redis.asyncio as redis
import structlog

from app.engine.recorder import RunRecorder

log = structlog.get_logger()

REGISTRY = "runs:active"


def _member(org_id: uuid.UUID, run_id: uuid.UUID) -> str:
    return f"{org_id}:{run_id}"


def _client(url: str) -> redis.Redis:
    return redis.from_url(url, socket_connect_timeout=2, socket_timeout=5)


async def announce(url: str, org_id: uuid.UUID, run_id: uuid.UUID, *, key: str = REGISTRY) -> None:
    """List a run as active, scored with Redis's own clock so workers need not agree on the time."""
    client = _client(url)
    try:
        seconds, _ = await client.time()
        await client.zadd(key, {_member(org_id, run_id): seconds})
    except (redis.RedisError, OSError, TimeoutError):
        log.warning("liveness.redis_unavailable")
    finally:
        await client.aclose()


async def forget(url: str, org_id: uuid.UUID, run_id: uuid.UUID, *, key: str = REGISTRY) -> None:
    client = _client(url)
    try:
        await client.zrem(key, _member(org_id, run_id))
    except (redis.RedisError, OSError, TimeoutError):
        log.warning("liveness.redis_unavailable")
    finally:
        await client.aclose()


async def stale_runs(
    url: str, older_than_seconds: float, *, key: str = REGISTRY
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(org_id, run_id) of runs listed as active whose last announcement is older than this."""
    client = _client(url)
    try:
        seconds, _ = await client.time()
        members = await client.zrangebyscore(key, "-inf", seconds - older_than_seconds)
    except (redis.RedisError, OSError, TimeoutError):
        log.warning("liveness.redis_unavailable")
        return []
    finally:
        await client.aclose()
    found: list[tuple[uuid.UUID, uuid.UUID]] = []
    for member in members:
        text = member.decode() if isinstance(member, bytes) else str(member)
        try:
            org, run = text.split(":", 1)
            found.append((uuid.UUID(org), uuid.UUID(run)))
        except ValueError:
            continue  # not ours; leave it alone
    return found


class Heartbeat:
    """Keeps a run's heartbeat going for as long as the block runs.

    `lost` becomes true if a beat finds that the run is no longer this worker's (another worker
    recovered it). The worker then stops at its very next write, which fencing refuses.
    """

    def __init__(
        self,
        recorder: RunRecorder,
        *,
        org_id: uuid.UUID,
        run_id: uuid.UUID,
        interval_seconds: float,
        redis_url: str | None,
        registry: str = REGISTRY,
    ) -> None:
        self._recorder = recorder
        self._org_id = org_id
        self._run_id = run_id
        self._interval = interval_seconds
        self._redis_url = redis_url
        self._registry = registry
        self._task: asyncio.Task[None] | None = None
        self.lost = False

    async def _beat(self) -> None:
        try:
            if not await self._recorder.heartbeat():
                self.lost = True
        except Exception:
            # A database hiccup must not kill the heartbeat: the next beat tries again.
            log.warning("liveness.beat_failed", exc_info=True)
        if self._redis_url:
            await announce(self._redis_url, self._org_id, self._run_id, key=self._registry)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self._beat()

    async def __aenter__(self) -> "Heartbeat":
        await self._beat()
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._redis_url:
            await forget(self._redis_url, self._org_id, self._run_id, key=self._registry)
