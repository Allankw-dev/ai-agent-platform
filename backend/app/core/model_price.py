"""The price of one model, as configured in MODEL_PRICES.

Lives in `core` (not `engine`) so that settings do not depend on the engine package.
"""

from decimal import Decimal

from pydantic import BaseModel


class ModelPrice(BaseModel):
    """USD per million tokens."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal
    # Some models charge more once a single prompt passes a size threshold.
    long_input_per_mtok: Decimal | None = None
    long_output_per_mtok: Decimal | None = None
    long_prompt_tokens: int = 200_000
