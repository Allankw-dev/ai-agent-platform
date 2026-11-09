import json
import uuid
from collections.abc import Callable

import httpx
import pytest

from app.core.auth_server import SupabaseAuthServer
from app.core.errors import ApiError

USER_ID = str(uuid.uuid4())


def _server(
    handler: Callable[[httpx.Request], httpx.Response], base: str = "https://abc.supabase.co"
) -> SupabaseAuthServer:
    return SupabaseAuthServer(base, "sb_publishable_test", transport=httpx.MockTransport(handler))


def _ok(**overrides: object) -> Callable[[httpx.Request], httpx.Response]:
    body: dict[str, object] = {
        "id": USER_ID,
        "email": "Ada@Example.com",
        "email_confirmed_at": "2026-11-07T10:00:00Z",
    }
    body.update(overrides)
    return lambda request: httpx.Response(200, json=body)


async def test_confirmed_user() -> None:
    user = await _server(_ok()).get_user("token-1")
    assert str(user.id) == USER_ID
    assert user.email == "ada@example.com"
    assert user.email_confirmed is True


async def test_asks_the_auth_server_with_the_users_token_and_the_public_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok()(request)

    await _server(handler, base="https://abc.supabase.co/").get_user("token-1")
    request = seen[0]
    assert str(request.url) == "https://abc.supabase.co/auth/v1/user"
    assert request.headers["authorization"] == "Bearer token-1"
    assert request.headers["apikey"] == "sb_publishable_test"


@pytest.mark.parametrize(
    "overrides",
    [
        {"email_confirmed_at": None},
        {"email_confirmed_at": ""},
        # a confirmed phone number must not count as a confirmed email
        {"email_confirmed_at": None, "confirmed_at": "2026-11-07T10:00:00Z"},
    ],
)
async def test_unconfirmed_email(overrides: dict[str, object]) -> None:
    user = await _server(_ok(**overrides)).get_user("t")
    assert user.email_confirmed is False


async def test_missing_confirmation_field_counts_as_unconfirmed() -> None:
    handler = lambda request: httpx.Response(200, json={"id": USER_ID, "email": "a@b.co"})  # noqa: E731
    assert (await _server(handler).get_user("t")).email_confirmed is False


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_token_is_a_401(status: int) -> None:
    server = _server(lambda request: httpx.Response(status, json={"msg": "bad jwt"}))
    with pytest.raises(ApiError) as caught:
        await server.get_user("t")
    assert caught.value.status_code == 401 and caught.value.code == "invalid_token"


@pytest.mark.parametrize("status", [429, 500, 502, 404])
async def test_other_failures_fail_closed_as_a_503(status: int) -> None:
    server = _server(lambda request: httpx.Response(status))
    with pytest.raises(ApiError) as caught:
        await server.get_user("t")
    assert caught.value.status_code == 503 and caught.value.code == "auth_unavailable"


@pytest.mark.parametrize("error", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
async def test_unreachable_auth_server_is_a_503(error: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(ApiError) as caught:
        await _server(handler).get_user("t")
    assert caught.value.status_code == 503


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        json.dumps({"email": "a@b.co"}).encode(),
        json.dumps({"id": "nope", "email": "a@b.co"}).encode(),
    ],
)
async def test_malformed_responses_fail_closed(body: bytes) -> None:
    server = _server(lambda request: httpx.Response(200, content=body))
    with pytest.raises(ApiError) as caught:
        await server.get_user("t")
    assert caught.value.status_code == 503
