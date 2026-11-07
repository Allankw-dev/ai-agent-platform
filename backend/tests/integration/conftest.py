"""Fixtures for tests that need a real PostgreSQL server.

Each test gets its own throwaway database, so tests never touch your dev data.
If Postgres is unreachable the tests are skipped, unless REQUIRE_DB=1 (used in CI),
in which case they fail loudly.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from alembic import command
from app.core.config import get_settings

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
