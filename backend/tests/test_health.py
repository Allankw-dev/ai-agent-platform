from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.health import check_database, check_redis
from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _override(database: bool, redis: bool) -> None:
    async def db() -> bool:
        return database

    async def rd() -> bool:
        return redis

    app.dependency_overrides[check_database] = db
    app.dependency_overrides[check_redis] = rd


async def test_liveness_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_ok_when_dependencies_up(client: AsyncClient) -> None:
    _override(database=True, redis=True)
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": True, "redis": True},
    }


@pytest.mark.parametrize(("database", "redis"), [(False, True), (True, False), (False, False)])
async def test_readiness_503_when_any_dependency_down(
    client: AsyncClient, database: bool, redis: bool
) -> None:
    _override(database=database, redis=redis)
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"] == {"database": database, "redis": redis}


async def test_unknown_route_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
