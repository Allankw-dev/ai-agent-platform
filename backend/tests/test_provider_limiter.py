"""The shared limits on model-provider calls. These need a real Redis (CI provides one)."""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import redis.asyncio as redis

from app.core.config import Settings, get_settings
from app.engine.llm import LLMError, LLMResponse
from app.engine.provider_limiter import LimitedLLM, ProviderBusy, ProviderLimiter
from tests.fakes import ScriptedLLM, reply


@pytest.fixture
async def prefix() -> AsyncIterator[str]:
    """A private set of Redis keys per test, removed afterwards."""
    name = f"test-limit-{uuid.uuid4().hex[:8]}"
    yield name
    client = redis.from_url(get_settings().redis_url)
    async for key in client.scan_iter(match=f"{name}:*"):
        await client.delete(key)
    await client.aclose()


def limiter(
    prefix: str,
    *,
    concurrent: int = 0,
    per_minute: int = 0,
    wait: float = 1.0,
    lease: float = 30.0,
    url: str | None = None,
) -> ProviderLimiter:
    return ProviderLimiter(
        url or get_settings().redis_url,
        max_concurrent={"gemini": concurrent} if concurrent else {},
        per_minute={"gemini": per_minute} if per_minute else {},
        wait_seconds=wait,
        lease_seconds=lease,
        prefix=prefix,
    )


async def test_a_provider_without_limits_never_touches_redis() -> None:
    free = ProviderLimiter(
        "redis://127.0.0.1:1/0",  # nothing listens here
        max_concurrent={},
        per_minute={},
        wait_seconds=0.1,
        lease_seconds=1,
    )
    async with free.slot("gemini"):
        pass


async def test_concurrent_calls_never_exceed_the_limit(prefix: str) -> None:
    gate = limiter(prefix, concurrent=3, wait=10)
    in_flight = 0
    peak = 0

    async def call() -> None:
        nonlocal in_flight, peak
        async with gate.slot("gemini"):
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.15)
            in_flight -= 1

    await asyncio.gather(*(call() for _ in range(10)))
    assert peak == 3  # it used the whole allowance and never more
    assert in_flight == 0


async def test_a_call_that_finds_the_provider_full_waits_then_gives_a_clear_failure(
    prefix: str,
) -> None:
    gate = limiter(prefix, concurrent=1, wait=0.4)
    async with gate.slot("gemini"):
        started = time.monotonic()
        with pytest.raises(ProviderBusy, match="busy with other runs"):
            async with gate.slot("gemini"):
                pytest.fail("should not have been let in")
        assert 0.35 <= time.monotonic() - started < 2
    async with gate.slot("gemini"):  # and the slot is free again afterwards
        pass


async def test_a_waiting_call_gets_in_as_soon_as_a_slot_frees(prefix: str) -> None:
    gate = limiter(prefix, concurrent=1, wait=5)
    order: list[str] = []

    async def first() -> None:
        async with gate.slot("gemini"):
            order.append("first in")
            await asyncio.sleep(0.3)
            order.append("first out")

    async def second() -> None:
        await asyncio.sleep(0.05)
        async with gate.slot("gemini"):
            order.append("second in")

    await asyncio.gather(first(), second())
    assert order == ["first in", "first out", "second in"]


async def test_a_slot_is_released_when_the_call_fails(prefix: str) -> None:
    gate = limiter(prefix, concurrent=1, wait=0.2)
    with pytest.raises(RuntimeError):
        async with gate.slot("gemini"):
            raise RuntimeError("the call blew up")
    async with gate.slot("gemini"):
        pass


async def test_a_worker_that_died_holding_a_slot_cannot_hold_it_forever(prefix: str) -> None:
    gate = limiter(prefix, concurrent=1, wait=0.1, lease=0.3)
    client = redis.from_url(get_settings().redis_url)
    assert await gate._try(client, "gemini", "dead-worker") == 1  # took it, never released
    assert await gate._try(client, "gemini", "someone-else") == 0  # full
    await asyncio.sleep(0.45)  # the lease runs out
    async with gate.slot("gemini"):
        pass
    await client.aclose()


async def test_calls_per_minute_are_counted_across_callers(prefix: str) -> None:
    gate = limiter(prefix, per_minute=3, wait=0.3)
    for _ in range(3):
        async with gate.slot("gemini"):
            pass
    with pytest.raises(ProviderBusy, match="calls-per-minute limit"):
        async with gate.slot("gemini"):
            pytest.fail("should not have been let in")


async def test_both_limits_apply_together(prefix: str) -> None:
    gate = limiter(prefix, concurrent=1, per_minute=2, wait=0.3)
    async with gate.slot("gemini"):
        with pytest.raises(ProviderBusy, match="busy with other runs"):
            async with gate.slot("gemini"):
                pass
    async with gate.slot("gemini"):  # the second call of the minute
        pass
    with pytest.raises(ProviderBusy, match="calls-per-minute"):
        async with gate.slot("gemini"):
            pass


async def test_providers_are_limited_separately(prefix: str) -> None:
    gate = ProviderLimiter(
        get_settings().redis_url,
        max_concurrent={"gemini": 1, "other": 1},
        per_minute={},
        wait_seconds=0.2,
        lease_seconds=30,
        prefix=prefix,
    )
    async with gate.slot("gemini"), gate.slot("other"):
        pass


async def test_if_redis_is_down_the_call_goes_ahead(prefix: str) -> None:
    gate = limiter(prefix, concurrent=1, wait=0.2, url="redis://127.0.0.1:1/0")
    ran = False
    async with gate.slot("gemini"):
        ran = True
    assert ran


async def test_a_limited_client_passes_everything_through_and_frees_the_slot(prefix: str) -> None:
    gate = limiter(prefix, concurrent=1, wait=0.2)
    inner = ScriptedLLM(reply("Hello"))
    client = LimitedLLM(inner, "gemini", gate)
    response: LLMResponse = await client.complete(
        model="m",
        system="s",
        messages=[{"role": "user", "text": "hi"}],
        tools=[],
        max_output_tokens=7,
    )
    assert response.text == "Hello"
    assert inner.requests[0]["model"] == "m" and inner.requests[0]["system"] == "s"
    # An error from the provider still frees the slot, and reaches the engine unchanged.
    failing = LimitedLLM(ScriptedLLM(), "gemini", gate)
    with pytest.raises(Exception):  # noqa: B017 (ScriptedLLM raises when it has nothing left)
        await failing.complete(model="m", system="s", messages=[], tools=[], max_output_tokens=None)
    async with gate.slot("gemini"):
        pass


async def test_a_busy_provider_is_an_ordinary_model_error_for_the_engine() -> None:
    assert issubclass(ProviderBusy, LLMError)


def test_the_limits_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MAX_CONCURRENT_CALLS", '{"gemini": 2, "other": 9}')
    monkeypatch.setenv("PROVIDER_CALLS_PER_MINUTE", '{"gemini": 12}')
    monkeypatch.setenv("PROVIDER_WAIT_SECONDS", "7")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "20")
    settings: Any = Settings()
    gate = ProviderLimiter.from_settings(settings)
    assert gate.limits_for("gemini") == (2, 12)
    assert gate.limits_for("other") == (9, 0)
    assert gate.limits_for("unlisted") == (0, 0)
    assert gate._wait == 7
    assert gate._lease_ms == (20 * 3 + 40) * 1000  # outlasts three tries of a slow call


def test_by_default_gemini_is_limited_to_four_calls_at_once() -> None:
    settings: Any = Settings()
    assert settings.provider_max_concurrent_calls == {"gemini": 4}
    assert settings.provider_calls_per_minute == {}
