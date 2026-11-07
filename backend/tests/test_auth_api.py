"""HTTP-level behaviour of authentication that does not need a database."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.deps import get_token_verifier
from app.core.config import Settings
from app.core.security import TokenVerifier
from app.main import app
from tests.auth_helpers import AUDIENCE, ISSUER, StaticKeys, new_key


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_missing_token_is_401_with_structured_error(client: AsyncClient) -> None:
    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        StaticKeys(new_key()), issuer=ISSUER, audience=AUDIENCE
    )
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_invalid_token_is_401(client: AsyncClient) -> None:
    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        StaticKeys(new_key()), issuer=ISSUER, audience=AUDIENCE
    )
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_auth_not_configured_is_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(_env_file=None, supabase_url=None))
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer x"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_not_configured"


async def test_unknown_route_uses_the_structured_shape(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"
