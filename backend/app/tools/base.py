"""Tool definitions, argument validation and the handler contract.

A tool has two halves. The *definition* lives in the `tools` table (the global catalog, seeded by
migrations): its key, description, JSON schema, whether it is sensitive and its timeout. The
*handler* is Python code registered under the same key (see `app.tools`). A catalog entry
without a handler cannot run, and a handler without a catalog entry is never offered to a model.

Arguments chosen by the model are untrusted input. They are validated against the tool's JSON
schema before a handler sees them (`validate_arguments`).
"""

import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from app.models.enums import IntegrationProvider

MAX_ERRORS_SHOWN = 3
MAX_ERROR_CHARS = 500

# Anthropic tool names may only contain letters, digits, underscores and hyphens.
_LLM_NAME_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]")


class ToolError(Exception):
    """A failure whose message is safe to show to the model (and to the run's audience)."""


class ToolArgumentsError(ToolError):
    """The model's arguments do not match the tool's schema."""


@dataclass(frozen=True)
class ResolvedIntegration:
    """An integration as a tool handler sees it: its settings and, if one is saved, its secret.

    The secret exists only inside this object, for the length of one tool call. It must never be
    logged, recorded in a run step or returned to the model (the repr hides it on purpose).
    """

    id: uuid.UUID
    provider: IntegrationProvider
    name: str
    config: dict[str, Any]
    secret: str | None = field(default=None, repr=False)


class IntegrationAccess(Protocol):
    """How a handler reaches the integration its tool grant points at."""

    async def resolve(
        self, integration_id: object, provider: IntegrationProvider
    ) -> ResolvedIntegration:
        """The integration with its current settings and decrypted secret.

        Raises ToolError (with a message safe to show) when it is missing, disabled, of the wrong
        type, or its secret cannot be used.
        """
        ...


@dataclass(frozen=True)
class ToolContext:
    """Who a tool call is running for. Handlers must never act outside this organization."""

    org_id: uuid.UUID
    agent_id: uuid.UUID
    run_id: uuid.UUID
    # How to reach this organization's integrations (None in tests that do not need them).
    integrations: IntegrationAccess | None = None
    # The settings of this agent's grant of the tool (for provider tools: {"integration_id": ...}).
    tool_config: Mapping[str, Any] = field(default_factory=dict)


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolDefinition:
    """A catalog entry as granted to one agent version."""

    id: uuid.UUID
    key: str
    description: str
    input_schema: dict[str, Any]
    is_sensitive: bool
    timeout_seconds: int
    requires_approval: bool = False
    config: dict[str, Any] | None = None

    @property
    def llm_name(self) -> str:
        """The name shown to the model: 'slack.send_message' becomes 'slack_send_message'."""
        return _LLM_NAME_UNSAFE.sub("_", self.key)[:64]

    @property
    def needs_approval(self) -> bool:
        """Sensitive tools always need a human; others only when the agent is configured so."""
        return self.is_sensitive or self.requires_approval

    def for_llm(self) -> dict[str, Any]:
        return {
            "name": self.llm_name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def validate_arguments(schema: dict[str, Any], arguments: Any) -> dict[str, Any]:
    """Return `arguments` if it satisfies `schema`, else raise ToolArgumentsError."""
    if not isinstance(arguments, dict):
        raise ToolArgumentsError("The tool arguments must be a JSON object.")
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path))
    if errors:
        shown = []
        for error in errors[:MAX_ERRORS_SHOWN]:
            location = ".".join(str(part) for part in error.absolute_path) or "(root)"
            shown.append(f"{location}: {error.message}")
        message = "Invalid arguments. " + "; ".join(shown)
        raise ToolArgumentsError(message[:MAX_ERROR_CHARS])
    return arguments
