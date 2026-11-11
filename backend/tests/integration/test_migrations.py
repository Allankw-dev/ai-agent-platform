from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from alembic import command
from app.models import Base
from tests.integration.conftest import alembic_config

EXPECTED_TABLES = {
    "users",
    "organizations",
    "organization_members",
    "organization_invitations",
    "tools",
    "agents",
    "agent_versions",
    "agent_tools",
    "integrations",
    "credentials",
    "agent_runs",
    "run_steps",
    "approvals",
    "conversations",
    "messages",
    "usage_records",
    "audit_logs",
}


def test_upgrade_creates_expected_tables(migrated_url: str) -> None:
    engine = create_engine(migrated_url)
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()
    assert tables == EXPECTED_TABLES


def test_downgrade_removes_everything(migrated_url: str) -> None:
    command.downgrade(alembic_config(migrated_url), "base")
    engine = create_engine(migrated_url)
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()
    assert tables == set()


def test_upgrade_downgrade_upgrade_is_repeatable(migrated_url: str) -> None:
    cfg = alembic_config(migrated_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(migrated_url)
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()
    assert tables == EXPECTED_TABLES


def test_models_match_migrations(migrated_url: str) -> None:
    """Fails if someone changes a model without adding a migration."""
    engine = create_engine(migrated_url)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert diff == []
