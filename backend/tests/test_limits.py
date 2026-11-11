from app.core.config import Settings
from app.engine.limits import effective_limits


def settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def test_agent_limits_apply_when_below_the_ceilings() -> None:
    limits = effective_limits(
        {
            "max_iterations": 3,
            "timeout_seconds": 30,
            "max_total_tokens": 2_000,
            "cost_budget_usd": 0.5,
        },
        settings(),
    )
    assert (limits.max_iterations, limits.timeout_seconds, limits.max_total_tokens) == (
        3,
        30,
        2_000,
    )
    assert limits.cost_budget_micro_usd == 500_000
    assert limits.cost_budget_usd == 0.5


def test_a_lowered_platform_ceiling_caps_an_older_version() -> None:
    limits = effective_limits(
        {
            "max_iterations": 20,
            "timeout_seconds": 200,
            "max_total_tokens": 400_000,
            "cost_budget_usd": 4,
        },
        settings(
            agent_max_iterations_ceiling=5,
            agent_timeout_ceiling_seconds=60,
            agent_token_budget_ceiling=10_000,
            agent_cost_budget_ceiling_usd=1.0,
        ),
    )
    assert (limits.max_iterations, limits.timeout_seconds, limits.max_total_tokens) == (
        5,
        60,
        10_000,
    )
    assert limits.cost_budget_micro_usd == 1_000_000


def test_no_cost_budget_means_no_cost_limit() -> None:
    limits = effective_limits({}, settings())
    assert limits.cost_budget_micro_usd is None
    assert limits.cost_budget_usd is None
    assert limits.max_iterations == 10  # the schema defaults apply
