from decimal import Decimal

from app.engine.pricing import ModelPrice, cost_micro_usd, micro_to_usd

PRICES = {
    "cheap": ModelPrice(input_per_mtok=Decimal("0.10"), output_per_mtok=Decimal("0.50")),
    "mid": ModelPrice(input_per_mtok=Decimal("2"), output_per_mtok=Decimal("10")),
    "tiered": ModelPrice(
        input_per_mtok=Decimal("1"),
        output_per_mtok=Decimal("2"),
        long_input_per_mtok=Decimal("2"),
        long_output_per_mtok=Decimal("4"),
        long_prompt_tokens=100_000,
    ),
}


def test_cost_is_price_times_tokens_in_micro_dollars() -> None:
    # $2 per million input and $10 per million output: 1000 in + 500 out = $0.002 + $0.005.
    cost = cost_micro_usd(PRICES, "mid", 1000, 500)
    assert cost == 7000
    assert micro_to_usd(cost) == Decimal("0.007")


def test_unknown_models_cost_nothing() -> None:
    assert cost_micro_usd(PRICES, "some-future-model", 10_000, 10_000) == 0
    assert cost_micro_usd({}, "mid", 10_000, 10_000) == 0


def test_long_prompts_use_the_higher_rate_when_the_model_has_one() -> None:
    assert cost_micro_usd(PRICES, "tiered", 100_000, 0) == 100_000  # $1 per million
    assert cost_micro_usd(PRICES, "tiered", 100_001, 0) == 200_002  # $2 per million


def test_models_without_a_long_rate_have_one_price() -> None:
    assert cost_micro_usd(PRICES, "mid", 900_000, 0) == 1_800_000


def test_fractions_of_a_micro_dollar_round_to_the_nearest() -> None:
    assert cost_micro_usd(PRICES, "cheap", 5, 0) == 1  # 0.5 rounds up
    assert cost_micro_usd(PRICES, "cheap", 4, 0) == 0
