from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.engine.pricing import ModelPrice


class Settings(BaseSettings):
    """Application settings, loaded from environment variables (and .env in development)."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "info"

    # Runtime connection: non-superuser role, so Row Level Security is enforced.
    database_url: str = "postgresql+psycopg://agent_app:agent_app@localhost:5432/agentplatform"
    # Migrations connection: owner role, used only by Alembic.
    migration_database_url: str = "postgresql+psycopg://app:app@localhost:5432/agentplatform"
    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = ["http://localhost:3000"]

    # Used to build invitation links, and how long an invitation stays valid.
    frontend_url: str = "http://localhost:3000"
    invitation_ttl_days: int = 7

    # Supabase Auth. The API only needs the project URL: tokens are verified against the
    # project's public keys (JWKS), so no secret is required here.
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    # The publishable key is public by design (it ships in the browser). The API uses it only to
    # ask Supabase's Auth server whether a user's email is confirmed. The same value as the
    # frontend's NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY, so no second variable is needed.
    supabase_publishable_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SUPABASE_PUBLISHABLE_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"
        ),
    )

    # LLM providers. Providers are swappable: each agent version names its provider and model.
    enabled_llm_providers: list[str] = ["gemini"]
    gemini_api_key: SecretStr | None = None
    # "free" means Google may use prompts to improve its products: development with fake data only.
    gemini_tier: Literal["free", "paid"] = "free"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    llm_timeout_seconds: float = 60.0
    # Estimated USD per million tokens, per model name. Empty by default because prices change
    # often: copy them from the provider's pricing page into MODEL_PRICES (JSON). A run whose
    # agent has a cost budget is refused for a model with no price here (see docs/engine.md).
    model_prices: dict[str, ModelPrice] = {}
    anthropic_api_key: SecretStr | None = None

    # Platform ceilings for per-agent run limits (agents may choose lower values).
    agent_max_iterations_ceiling: int = 25
    agent_timeout_ceiling_seconds: int = 300
    agent_token_budget_ceiling: int = 500_000
    agent_cost_budget_ceiling_usd: float = 5.0

    # Credential encryption (Phase 4)
    credential_encryption_key: SecretStr | None = None

    sentry_dsn: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
