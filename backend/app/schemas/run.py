import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import RunEventType, RunStatus, RunTrigger, StepStatus, StepType
from app.schemas.approval import ApprovalSummary


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=20_000)]
    trigger: Literal["manual", "test"] = "manual"

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class RunRead(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    agent_version_id: uuid.UUID
    agent_version: int
    status: RunStatus
    trigger: RunTrigger
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float  # an estimate, see app/engine/pricing.py
    # 1 normally; 2 or more when the run was taken over after its worker was lost.
    attempt: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunStepRead(BaseModel):
    id: uuid.UUID
    sequence: int
    step_type: StepType
    status: StepStatus
    name: str | None
    tool_key: str | None
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: str | None
    input_tokens: int
    output_tokens: int
    started_at: datetime
    finished_at: datetime | None


class RunDetail(RunRead):
    steps: list[RunStepRead]
    # Set while the run waits for a person's decision.
    pending_approval: ApprovalSummary | None = None


class RunEventRead(BaseModel):
    """One thing that happened to a run. `data` holds ids and statuses only."""

    model_config = ConfigDict(from_attributes=True)

    seq: int
    type: RunEventType
    data: dict[str, Any]
    created_at: datetime


class RunEventList(BaseModel):
    items: list[RunEventRead]
