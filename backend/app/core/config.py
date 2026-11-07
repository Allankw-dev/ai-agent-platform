from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables (and .env in development)."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "info"

    # Runtime connection: non-superuser role, so Row Level Security is enforced.
    database_url: str = "postgresql+psycopg://agent_app:agent_app@localhost:5432/agentplatform"
    # Migrations connection: owner role, used only by Alembic.
    migration_database_url: str = "postgresql+psycopg://app:app@localhost:5432/agentplatform"
    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = ["http://localhost:3000"]

    # Supabase (Phase 2)
    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_jwt_secret: SecretStr | None = None

    # Anthropic (Phase 3)
    anthropic_api_key: SecretStr | None = None

    # Credential encryption (Phase 4)
    credential_encryption_key: SecretStr | None = None

    sentry_dsn: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
