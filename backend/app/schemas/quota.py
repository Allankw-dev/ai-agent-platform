import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrgLimitsRead(BaseModel):
    """What this organization may run. `customized` is false while platform defaults apply."""

    max_concurrent_runs: int
    daily_token_quota: int
    daily_cost_quota_usd: float | None
    customized: bool
    updated_at: datetime | None


class OrgLimitsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_concurrent_runs: int = Field(ge=1, le=1_000)
    daily_token_quota: int = Field(ge=1_000, le=2_000_000_000)
    daily_cost_quota_usd: Decimal | None = Field(
        default=None, gt=0, le=1_000_000, max_digits=12, decimal_places=6
    )


class UsageToday(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    # What runs that are still open may yet use (their reservation minus what they have spent).
    reserved_tokens: int
    # Runs queued or running right now.
    busy_runs: int
    resets_at: datetime


class UsageDay(BaseModel):
    day: date
    runs: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AgentUsage(BaseModel):
    agent_id: uuid.UUID
    agent_name: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UsageRead(BaseModel):
    limits: OrgLimitsRead
    today: UsageToday
    days: list[UsageDay]
    by_agent: list[AgentUsage]
