"""CORS preflight: what a browser asks before it sends a cross-origin request.

The web app (localhost:3000) calls the API (localhost:8000), so the browser first asks which
methods and headers are allowed. A header missing from the answer makes the browser block the real
request, which the app reports as "Could not reach the server".
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

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
