"""The tool registry: Python handlers keyed by the catalog's tool key."""

from collections.abc import Callable
from typing import Any

from app.tools.base import ToolHandler

# Turns validated arguments into their final form (for example, making message text safe). It must
# be idempotent: preparing twice gives the same result as preparing once. The engine runs it before
# a tool executes, and the approval screens use it so a person sees exactly what will be sent.
ArgumentPreparer = Callable[[dict[str, Any]], dict[str, Any]]

_HANDLERS: dict[str, ToolHandler] = {}
_PREPARERS: dict[str, ArgumentPreparer] = {}


def register(
    key: str, *, prepare: ArgumentPreparer | None = None
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator that registers `handler` as the implementation of catalog tool `key`."""

    def decorator(handler: ToolHandler) -> ToolHandler:
        if key in _HANDLERS:
            raise RuntimeError(f"A handler for tool {key!r} is already registered.")
        _HANDLERS[key] = handler
        if prepare is not None:
            _PREPARERS[key] = prepare
        return handler

    return decorator


def get_handler(key: str) -> ToolHandler | None:
    return _HANDLERS.get(key)


def prepare_arguments(key: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """The final form of a tool's arguments (unchanged for tools with no preparer)."""
    preparer = _PREPARERS.get(key)
    return preparer(arguments) if preparer else arguments


def registered_keys() -> frozenset[str]:
    return frozenset(_HANDLERS)


# Importing the modules registers their handlers.
from app.tools import builtin, http, slack  # noqa: E402, F401
