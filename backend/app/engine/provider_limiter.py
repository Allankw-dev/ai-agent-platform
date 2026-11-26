"""Limits on how hard the platform leans on a model provider, shared by every worker.

Provider quotas (Gemini's free tier especially) are small and per project, not per worker, so the
count has to live somewhere every worker can see: Redis. Two limits, both optional per provider:

- concurrent calls in flight, and
- calls started per minute.

Each call takes a *lease* that expires on its own, so a worker that dies mid-call cannot hold a slot
forever. A call that finds the provider full waits briefly (the wait counts against the run's own
time limit) and then fails with a clear message. If Redis itself cannot be reached the call goes
ahead and a warning is logged: this protects the provider quota, it is not a security control, and
refusing every run because Redis blinked would be worse than the thing it prevents.
"""

import asyncio
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis
import structlog

from app.core.config import Settings
from app.engine.llm import LLMClient, LLMError, LLMResponse, Message, ToolSpec

log = structlog.get_logger()

# One atomic step: drop expired leases and old window entries, then take a lease if both limits
# allow. Uses Redis's own clock so workers with different clocks agree.
# Returns 1 (taken), 0 (concurrent calls full) or 2 (calls per minute used up).
ACQUIRE = """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local slots, window = KEYS[1], KEYS[2]
local token, lease_ms = ARGV[1], tonumber(ARGV[2])
local max_calls, rpm = tonumber(ARGV[3]), tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', slots, '-inf', now)
if max_calls > 0 and redis.call('ZCARD', slots) >= max_calls then return 0 end
if rpm > 0 then
  redis.call('ZREMRANGEBYSCORE', window, '-inf', now - 60000)
  if redis.call('ZCARD', window) >= rpm then return 2 end
  redis.call('ZADD', window, now, token)
  redis.call('PEXPIRE', window, 120000)
end
redis.call('ZADD', slots, now + lease_ms, token)
redis.call('PEXPIRE', slots, lease_ms * 2)
return 1
"""

POLL_SECONDS = 0.25


class ProviderBusy(LLMError):
    """The provider's limits stayed full for the whole wait."""


class ProviderLimiter:
    def __init__(
        self,
        url: str,
        *,
        max_concurrent: dict[str, int],
        per_minute: dict[str, int],
        wait_seconds: float,
        lease_seconds: float,
        prefix: str = "provider-limit",
    ) -> None:
        self._url = url
        self._max_concurrent = max_concurrent
        self._per_minute = per_minute
        self._wait = wait_seconds
        self._lease_ms = int(lease_seconds * 1000)
        self._prefix = prefix

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProviderLimiter":
        # A call can retry twice after a timeout or 429, so a lease must outlast all three tries.
        lease = settings.llm_timeout_seconds * 3 + 40
        return cls(
            settings.redis_url,
            max_concurrent=settings.provider_max_concurrent_calls,
            per_minute=settings.provider_calls_per_minute,
            wait_seconds=settings.provider_wait_seconds,
            lease_seconds=lease,
        )

    def limits_for(self, provider: str) -> tuple[int, int]:
        return self._max_concurrent.get(provider, 0), self._per_minute.get(provider, 0)

    async def _try(self, client: Any, provider: str, token: str) -> int:
        max_calls, per_minute = self.limits_for(provider)
        result = await client.eval(
            ACQUIRE,
            2,
            f"{self._prefix}:{provider}:slots",
            f"{self._prefix}:{provider}:window",
            token,
            self._lease_ms,
            max_calls,
            per_minute,
        )
        return int(result)

    @asynccontextmanager
    async def slot(self, provider: str) -> AsyncIterator[None]:
        """Hold one of the provider's call slots for the duration of the block."""
        if self.limits_for(provider) == (0, 0):
            yield
            return
        token = uuid.uuid4().hex
        client = redis.from_url(self._url, socket_connect_timeout=2, socket_timeout=5)
        taken = False
        try:
            deadline = time.monotonic() + self._wait
            while True:
                try:
                    verdict = await self._try(client, provider, token)
                except (redis.RedisError, OSError, TimeoutError):
                    log.warning("provider_limiter.redis_unavailable", provider=provider)
                    break  # fail open: see the module docstring
                if verdict == 1:
                    taken = True
                    break
                if time.monotonic() >= deadline:
                    raise ProviderBusy(self._busy_message(provider, verdict))
                await asyncio.sleep(POLL_SECONDS + random.uniform(0, POLL_SECONDS / 2))  # noqa: S311 (jitter, not security)
            yield
        finally:
            if taken:
                try:
                    await client.zrem(f"{self._prefix}:{provider}:slots", token)
                except (redis.RedisError, OSError, TimeoutError):
                    log.warning("provider_limiter.release_failed", provider=provider)
            await client.aclose()

    def _busy_message(self, provider: str, verdict: int) -> str:
        if verdict == 2:
            return (
                f"The {provider} provider's calls-per-minute limit on this platform is used up "
                "right now. Try again in a minute."
            )
        return (
            f"The {provider} provider is busy with other runs on this platform right now. "
            "Try again in a moment."
        )


class LimitedLLM:
    """Any model client, made to take a slot from the limiter for each call."""

    def __init__(self, inner: LLMClient, provider: str, limiter: ProviderLimiter) -> None:
        self._inner = inner
        self._provider = provider
        self._limiter = limiter

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_output_tokens: int | None,
    ) -> LLMResponse:
        async with self._limiter.slot(self._provider):
            return await self._inner.complete(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_output_tokens=max_output_tokens,
            )
