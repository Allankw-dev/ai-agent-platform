"""CORS preflight: what a browser asks before it sends a cross-origin request.

The web app (localhost:3000) calls the API (localhost:8000), so the browser first asks which
methods and headers are allowed. A header missing from the answer makes the browser block the real
request, which the app reports as "Could not reach the server".
"""

from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app, create_app

ORIGIN = "http://localhost:3000"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def preflight(method: str, headers: str, origin: str = ORIGIN) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": headers,
    }


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
async def test_the_headers_the_web_app_sends_are_allowed(client: AsyncClient, method: str) -> None:
    response = await client.options(
        "/api/v1/organizations",
        headers=preflight(method, "authorization,content-type,idempotency-key"),
    )
    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    for header in ("authorization", "content-type", "idempotency-key"):
        assert header in allowed
    assert response.headers["access-control-allow-origin"] == ORIGIN


async def test_starting_a_run_passes_the_preflight(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/organizations/00000000-0000-0000-0000-000000000000/agents/"
        "00000000-0000-0000-0000-000000000000/runs",
        headers=preflight("POST", "authorization,content-type,idempotency-key"),
    )
    assert response.status_code == 200


async def test_resuming_an_event_stream_passes_the_preflight(client: AsyncClient) -> None:
    zero = "00000000-0000-0000-0000-000000000000"
    response = await client.options(
        f"/api/v1/organizations/{zero}/runs/{zero}/events/stream",
        headers=preflight("GET", "authorization,last-event-id"),
    )
    assert response.status_code == 200
    assert "last-event-id" in response.headers["access-control-allow-headers"].lower()


async def test_unexpected_headers_are_still_refused(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/organizations", headers=preflight("POST", "authorization,x-something-else")
    )
    assert response.status_code == 400


async def test_other_websites_are_refused(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/organizations",
        headers=preflight("POST", "authorization", origin="https://evil.example.com"),
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


# ---------- a different WEB_PORT ----------


@pytest.fixture
def web_on_port_3001(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """What docker-compose passes to the API when WEB_PORT=3001 is set in .env."""
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3001"]')
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3001")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_web_port_setting_reaches_the_api_settings(web_on_port_3001: None) -> None:
    settings = get_settings()
    assert settings.cors_origins == ["http://localhost:3001"]
    assert settings.frontend_url == "http://localhost:3001"


async def test_the_api_accepts_the_website_on_the_new_port_and_not_the_old_one(
    web_on_port_3001: None,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        allowed = await c.options(
            "/api/v1/organizations",
            headers=preflight(
                "POST", "authorization,idempotency-key", origin="http://localhost:3001"
            ),
        )
        refused = await c.options(
            "/api/v1/organizations",
            headers=preflight(
                "POST", "authorization,idempotency-key", origin="http://localhost:3000"
            ),
        )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3001"
    assert refused.status_code == 400


def test_invitation_links_use_the_configured_website(web_on_port_3001: None) -> None:
    assert (
        get_settings().frontend_url.rstrip("/") + "/invite/abc"
        == "http://localhost:3001/invite/abc"
    )
