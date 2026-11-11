"""The tool registry: Python handlers keyed by the catalog's tool key."""

from collections.abc import Callable

from app.tools.base import ToolHandler

_HANDLERS: dict[str, ToolHandler] = {}


def register(key: str) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator that registers `handler` as the implementation of catalog tool `key`."""

    def decorator(handler: ToolHandler) -> ToolHandler:
        if key in _HANDLERS:
            raise RuntimeError(f"A handler for tool {key!r} is already registered.")
        _HANDLERS[key] = handler
        return handler

    return decorator


def get_handler(key: str) -> ToolHandler | None:
    return _HANDLERS.get(key)


def registered_keys() -> frozenset[str]:
    return frozenset(_HANDLERS)


# Importing the modules registers their handlers.
from app.tools import builtin  # noqa: E402, F401
