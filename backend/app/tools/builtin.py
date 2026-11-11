"""Built-in tools that touch nothing outside the process: safe to run without approval."""

import ast
import operator
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.tools import register
from app.tools.base import ToolContext, ToolError

# ---------- utility.current_time ----------


@register("utility.current_time")
async def current_time(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    name = arguments.get("timezone", "UTC")
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ToolError(
            f"Unknown timezone: {name!r}. Use an IANA name such as 'Africa/Nairobi'."
        ) from exc
    now = datetime.now(zone)
    return {
        "iso": now.isoformat(timespec="seconds"),
        "timezone": name,
        "weekday": now.strftime("%A"),
    }


# ---------- utility.calculate ----------
# A tiny arithmetic evaluator over the AST. No names, calls or attributes are ever evaluated,
# and magnitudes are capped so that "9**9**9" cannot burn CPU or memory.

MAX_MAGNITUDE = 10**100
MAX_EXPONENT = 100
MAX_EXPRESSION_CHARS = 200

Number = int | float


def _check(value: Number) -> Number:
    if isinstance(value, float) and value != value:  # NaN
        raise ToolError("The result is not a number.")
    if abs(value) > MAX_MAGNITUDE:
        raise ToolError("The result is too large.")
    return value


def _power(base: Number, exponent: Number) -> Number:
    if abs(exponent) > MAX_EXPONENT:
        raise ToolError(f"Exponents larger than {MAX_EXPONENT} are not supported.")
    try:
        result = base**exponent
    except ZeroDivisionError as exc:
        raise ToolError("Division by zero.") from exc
    if isinstance(result, complex):
        raise ToolError("The result is not a real number.")
    return result


_BINARY: dict[type[ast.operator], Callable[[Any, Any], Number]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _power,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Number]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _evaluate(node: ast.AST) -> Number:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        if isinstance(node.value, bool):
            raise ToolError("Booleans are not numbers.")
        return _check(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        try:
            return _check(_BINARY[type(node.op)](left, right))
        except ZeroDivisionError as exc:
            raise ToolError("Division by zero.") from exc
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _check(_UNARY[type(node.op)](_evaluate(node.operand)))
    raise ToolError("Only numbers and the operators + - * / // % ** and parentheses are allowed.")


@register("utility.calculate")
async def calculate(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    expression = str(arguments["expression"])
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ToolError(f"The expression is longer than {MAX_EXPRESSION_CHARS} characters.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ToolError("That is not a valid arithmetic expression.") from exc
    try:
        result = _evaluate(tree.body)
    except RecursionError as exc:
        raise ToolError("The expression is nested too deeply.") from exc
    return {"expression": expression.strip(), "result": result}
