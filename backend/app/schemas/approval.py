"""Request and response shapes for approvals (a person deciding on an agent's action)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ApprovalStatus

MAX_NOTE_CHARS = 500


class ApprovalDecision(BaseModel):
    """The body of approve and reject. The note is optional and is shown to the agent."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)

    @field_validator("note")
    @classmethod
    def _tidy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.replace("\x00", "").strip()
        return cleaned or None


class ApprovalSummary(BaseModel):
    """What a run page needs to say "waiting for approval" and link to it."""

    id: uuid.UUID
    tool_key: str
    requested_at: datetime
    expires_at: datetime | None
    seconds_left: int | None


class ApprovalRead(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    run_step_id: uuid.UUID | None
    agent_id: uuid.UUID
    agent_name: str
    agent_version: int
    tool_key: str
    tool_name: str | None
    # Exactly what will run if this is approved: the checked, final form of the arguments.
    proposed_input: dict[str, Any]
    # What the model said when it asked for the action (it is the model's claim, not a fact).
    reasoning_summary: str | None
    status: ApprovalStatus
    requested_at: datetime
    expires_at: datetime | None
    seconds_left: int | None
    decided_by_id: uuid.UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
