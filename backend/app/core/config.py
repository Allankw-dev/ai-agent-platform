from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.model_price import ModelPrice


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
    agent_max_tool_calls_ceiling: int = 100
    agent_timeout_ceiling_seconds: int = 300
    agent_token_budget_ceiling: int = 500_000
    agent_cost_budget_ceiling_usd: float = 5.0

    # How long a person has to approve or reject an action before it expires (Phase 4).
    approval_expiry_hours: int = Field(default=24, ge=1, le=168)

    # Run limits for an organization that has not set its own (Phase 5B). A run reserves its token
    # budget against the daily quota when it is created, so these also bound simultaneous starts.
    org_default_max_concurrent_runs: int = Field(default=5, ge=1)
    org_default_daily_token_quota: int = Field(default=500_000, ge=1_000)
    org_default_daily_cost_quota_usd: Decimal | None = Field(default=None, gt=0)

    # How hard the platform may lean on a model provider, across all workers (Phase 5B). Both are
    # per provider name; a provider that is not listed is unlimited. Calls wait up to
    # PROVIDER_WAIT_SECONDS for a free slot and then fail with a clear message.
    provider_max_concurrent_calls: dict[str, int] = {"gemini": 4}
    provider_calls_per_minute: dict[str, int] = {}
    provider_wait_seconds: float = Field(default=30.0, gt=0)

    # Live run streaming (Phase 5A): how often the stream looks for new events, how often it
    # sends a keep-alive when nothing happened, and how long one connection lives before the
    # client reconnects from the last sequence number it saw.
    run_stream_poll_seconds: float = Field(default=1.0, gt=0, le=10)
    run_stream_heartbeat_seconds: float = Field(default=15.0, gt=0)
    run_stream_max_seconds: float = Field(default=300.0, gt=0)

    # Credential encryption (Phase 4)
    credential_encryption_key: SecretStr | None = None

    sentry_dsn: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
