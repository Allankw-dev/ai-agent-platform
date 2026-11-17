import logging
import re
import sys
from typing import Any

import structlog

# Log fields whose names suggest a secret. Their values are never written to the logs.
_SENSITIVE_NAME = re.compile(
    r"(token|secret|authorization|password|passwd|api[_-]?key|credential|cookie)", re.IGNORECASE
)
REDACTED = "[redacted]"


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            key: REDACTED
            if isinstance(key, str) and _SENSITIVE_NAME.search(key)
            else _scrub(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_scrub(item, depth + 1) for item in value]
    return value


def redact_sensitive(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """A structlog processor: hide the value of any field named like a secret."""
    return _scrub(event_dict)  # type: ignore[no-any-return]


def configure_logging(level: str, json_logs: bool) -> None:
    """Configure structlog. JSON output in production, readable console output otherwise."""
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            redact_sensitive,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )
