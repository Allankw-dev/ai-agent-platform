"""GET /auth/me against a real database: first-login provisioning and conflicts."""

import uuid
from collections.abc import AsyncIterator

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_token_verifier
from app.core.security import TokenVerifier
from app.db.session import get_session
from app.main import app
from tests.auth_helpers import AUDIENCE, ISSUER, StaticKeys, make_token, new_key


@pytest.fixture
def signing_key() -> ec.EllipticCurvePrivateKey:
    return new_key()


@pytest.fixture
async def client(
    runtime_url: str, migrated_url: str, signing_key: ec.EllipticCurvePrivateKey
) -> AsyncIterator[AsyncClient]:
    # The API talks to the database as the restricted runtime role, so RLS really applies.
    engine = create_async_engine(runtime_url)
    owner_engine = create_async_engine(migrated_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        StaticKeys(signing_key), issuer=ISSUER, audience=AUDIENCE
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.engine = owner_engine  # type: ignore[attr-defined]  # counts rows, bypassing RLS
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()
    await owner_engine.dispose()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user_count(client: AsyncClient) -> int:
    async with client.engine.connect() as conn:  # type: ignore[attr-defined]
        return int((await conn.execute(text("SELECT count(*) FROM users"))).scalar_one())


async def test_first_login_creates_the_profile(
    client: AsyncClient, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    user_id = uuid.uuid4()
    token = make_token(signing_key, user_id=user_id, email="ada@example.com")
    response = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["email"] == "ada@example.com"
    assert body["is_super_admin"] is False
    assert await _user_count(client) == 1


async def test_repeat_logins_do_not_duplicate(
    client: AsyncClient, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    token = make_token(signing_key, user_id=uuid.uuid4())
    for _ in range(3):
        assert (await client.get("/api/v1/auth/me", headers=_auth(token))).status_code == 200
    assert await _user_count(client) == 1


async def test_changed_email_is_synced(
    client: AsyncClient, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    user_id = uuid.uuid4()
    await client.get(
        "/api/v1/auth/me", headers=_auth(make_token(signing_key, user_id=user_id, email="a@x.com"))
    )
    response = await client.get(
        "/api/v1/auth/me", headers=_auth(make_token(signing_key, user_id=user_id, email="b@x.com"))
    )
    assert response.json()["email"] == "b@x.com"
    assert await _user_count(client) == 1


async def test_email_belonging_to_another_account_is_a_409(
    client: AsyncClient, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    first = make_token(signing_key, user_id=uuid.uuid4(), email="same@x.com")
    second = make_token(signing_key, user_id=uuid.uuid4(), email="same@x.com")
    assert (await client.get("/api/v1/auth/me", headers=_auth(first))).status_code == 200
    response = await client.get("/api/v1/auth/me", headers=_auth(second))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_conflict"
    assert await _user_count(client) == 1
