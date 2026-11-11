"""Fixtures for tests that need a real PostgreSQL server.

Each test gets its own throwaway database, so tests never touch your dev data.
If Postgres is unreachable the tests are skipped, unless REQUIRE_DB=1 (used in CI),
in which case they fail loudly.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from alembic import command
from app.core.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.integration.api_helpers import Api
    from tests.integration.engine_helpers import Queue, Workspace

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _admin_engine() -> Engine:
    return create_engine(
        get_settings().migration_database_url, isolation_level="AUTOCOMMIT", poolclass=None
    )


def _require_or_skip(reason: str) -> None:
    if os.environ.get("REQUIRE_DB") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture
def db_url() -> Iterator[str]:
    """Create an empty temporary database; drop it afterwards. Yields its URL."""
    name = f"test_{uuid.uuid4().hex[:12]}"
    admin = _admin_engine()
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        _require_or_skip("PostgreSQL is not reachable (start it with: docker compose up -d db)")
    url = make_url(get_settings().migration_database_url).set(database=name)
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture
def migrated_url(db_url: str) -> str:
    command.upgrade(alembic_config(db_url), "head")
    return db_url


@pytest.fixture
def engine(migrated_url: str) -> Iterator[Engine]:
    eng = create_engine(migrated_url)
    yield eng
    eng.dispose()


def runtime_role_exists(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'agent_app'")).scalar()
        )


@pytest.fixture
def runtime_url(migrated_url: str) -> str:
    """URL for the non-superuser runtime role (agent_app), the role the API really uses.

    Row Level Security does not apply to superusers, so isolation must be tested as this role.
    """
    owner = create_engine(migrated_url)
    try:
        exists = runtime_role_exists(owner)
    finally:
        owner.dispose()
    if not exists:
        _require_or_skip("runtime role agent_app is missing (see docker/postgres-init.sql)")
    url = make_url(migrated_url).set(username="agent_app", password="agent_app")
    return url.render_as_string(hide_password=False)


@pytest.fixture
async def api(runtime_url: str, engine: Engine) -> AsyncIterator["Api"]:
    """The real FastAPI app on a fresh migrated database, connected as the restricted role."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.api.deps import get_auth_server, get_token_verifier
    from app.core.security import TokenVerifier
    from app.db.session import get_session
    from app.main import app
    from tests.auth_helpers import AUDIENCE, ISSUER, StaticKeys, new_key
    from tests.integration.api_helpers import Api

    key = new_key()
    runtime_engine = create_async_engine(runtime_url)
    maker = async_sessionmaker(runtime_engine, expire_on_commit=False)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        StaticKeys(key), issuer=ISSUER, audience=AUDIENCE
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        api_driver = Api(client, key, engine)
        app.dependency_overrides[get_auth_server] = lambda: api_driver.auth_server
        yield api_driver
    app.dependency_overrides.clear()
    await runtime_engine.dispose()


@pytest.fixture
def gemini_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make the platform believe a Gemini key is configured (no real call is ever made)."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def workspace(api: "Api") -> "Workspace":
    from tests.integration.engine_helpers import ADMIN, DEV, MEMBER, OWNER, STRANGER, Workspace

    org = await api.create_org(OWNER, "Acme Inc")
    await api.add_member(org["id"], ADMIN, "admin")
    await api.add_member(org["id"], DEV, "developer")
    await api.add_member(org["id"], MEMBER, "member")
    other = await api.create_org(STRANGER, "Other Co")
    return Workspace(api=api, org_id=org["id"], other_org_id=other["id"])


@pytest.fixture
def queue(api: "Api") -> Iterator["Queue"]:
    """Replace Celery with a recorder for the duration of a test."""
    from app.api.deps import get_run_dispatcher
    from app.main import app
    from tests.integration.engine_helpers import Queue

    recorder = Queue()
    app.dependency_overrides[get_run_dispatcher] = lambda: recorder.dispatch
    yield recorder
    app.dependency_overrides.pop(get_run_dispatcher, None)


@pytest.fixture
async def runtime_maker(runtime_url: str) -> AsyncIterator["async_sessionmaker[AsyncSession]"]:
    """Sessions as the restricted runtime role, like the Celery worker uses."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    runtime_engine = create_async_engine(runtime_url)
    yield async_sessionmaker(runtime_engine, expire_on_commit=False)
    await runtime_engine.dispose()
