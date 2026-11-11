"""Cost estimates for model calls.

Prices are USD per million tokens. A token costs that many millionths of a dollar per dollar of
price, so `price * tokens` is the cost in micro-dollars. Everything is computed as an integer
number of micro-dollars to avoid floating point drift; `Numeric(12, 6)` in the database holds the
same value in dollars.

There is deliberately no built-in price list: provider prices and model names change often, and a
stale hard-coded number would silently give wrong budgets. Configure prices with the MODEL_PRICES
environment variable, for example (check your provider's pricing page for real numbers):

    MODEL_PRICES={"gemini-3.5-flash": {"input_per_mtok": "<n>", "output_per_mtok": "<n>"}}

Output tokens include any hidden "thinking" tokens, because providers bill them as output.
"""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel


class ModelPrice(BaseModel):
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    # Some models charge more once a single prompt passes a size threshold.
    long_input_per_mtok: Decimal | None = None
    long_output_per_mtok: Decimal | None = None
    long_prompt_tokens: int = 200_000


def cost_micro_usd(
    prices: dict[str, ModelPrice], model: str, input_tokens: int, output_tokens: int
) -> int:
    """Estimated cost of one call in millionths of a dollar. Unknown models cost 0."""
    price = prices.get(model)
    if price is None:
        return 0
    input_rate, output_rate = price.input_per_mtok, price.output_per_mtok
    if (
        price.long_input_per_mtok is not None
        and price.long_output_per_mtok is not None
        and input_tokens > price.long_prompt_tokens
    ):
        input_rate, output_rate = price.long_input_per_mtok, price.long_output_per_mtok
    total = input_rate * input_tokens + output_rate * output_tokens
    return int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def micro_to_usd(micro: int) -> Decimal:
    return Decimal(micro) / Decimal(1_000_000)
