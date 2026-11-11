"""The limits that actually apply to a run: the agent's own, capped by the platform's ceilings."""

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.schemas.agent import Limits


@dataclass(frozen=True)
class EffectiveLimits:
    max_iterations: int  # model calls per run
    timeout_seconds: int
    max_total_tokens: int
    cost_budget_micro_usd: int | None

    @property
    def cost_budget_usd(self) -> float | None:
        if self.cost_budget_micro_usd is None:
            return None
        return self.cost_budget_micro_usd / 1_000_000


def effective_limits(raw: dict[str, Any], settings: Settings) -> EffectiveLimits:
    """The agent version's limits, lowered to the platform ceilings if those were lowered later."""
    limits = Limits.model_validate(raw)
    budget = limits.cost_budget_usd
    if budget is not None:
        budget = min(budget, settings.agent_cost_budget_ceiling_usd)
    return EffectiveLimits(
        max_iterations=min(limits.max_iterations, settings.agent_max_iterations_ceiling),
        timeout_seconds=min(limits.timeout_seconds, settings.agent_timeout_ceiling_seconds),
        max_total_tokens=min(limits.max_total_tokens, settings.agent_token_budget_ceiling),
        cost_budget_micro_usd=None if budget is None else round(budget * 1_000_000),
    )
