import json
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import LLMProvider

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
TOOL_KEY_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
MAX_TOOL_CONFIG_BYTES = 10_000


class ModelParams(BaseModel):
    """Generation settings. Only settings every supported model accepts are offered, so there is
    deliberately no temperature (newer models reject non-default values)."""

    model_config = ConfigDict(extra="forbid")

    max_output_tokens: int | None = Field(default=None, ge=1, le=65_536)


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_memory: bool = True
    max_history_messages: int = Field(default=20, ge=1, le=200)


class Limits(BaseModel):
    """Per-run limits. The platform enforces ceilings on top of these (see the agent service)."""

    model_config = ConfigDict(extra="forbid")

    max_iterations: int = Field(default=10, ge=1)
    timeout_seconds: int = Field(default=120, ge=5)
    max_total_tokens: int = Field(default=50_000, ge=1_000)
    cost_budget_usd: float | None = Field(default=None, gt=0)


class ToolAssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_key: str = Field(max_length=100)
    requires_approval: bool = False
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_key")
    @classmethod
    def _key_shape(cls, value: str) -> str:
        if not TOOL_KEY_PATTERN.match(value):
            raise ValueError("tool_key must look like 'group.name'")
        return value

    @field_validator("config")
    @classmethod
    def _small_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > MAX_TOOL_CONFIG_BYTES:
            raise ValueError("tool config is too large")
        return value


class AgentConfig(BaseModel):
    """Everything that defines how an agent behaves. Saved as an immutable version."""

    model_config = ConfigDict(extra="forbid")

    provider: LLMProvider = LLMProvider.GEMINI
    model: str = Field(min_length=1, max_length=100)
    system_instructions: str = Field(min_length=1, max_length=20_000)
    objectives: str | None = Field(default=None, max_length=4_000)
    model_params: ModelParams = Field(default_factory=ModelParams)
    memory_config: MemoryConfig = Field(default_factory=MemoryConfig)
    limits: Limits = Field(default_factory=Limits)
    tools: list[ToolAssignmentIn] = Field(default_factory=list, max_length=50)

    @field_validator("model")
    @classmethod
    def _model_shape(cls, value: str) -> str:
        value = value.strip()
        if not NAME_PATTERN.match(value):
            raise ValueError("model contains characters that are not allowed")
        return value

    @field_validator("system_instructions")
    @classmethod
    def _instructions_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instructions cannot be blank")
        return value

    @field_validator("objectives")
    @classmethod
    def _objectives_blank_is_none(cls, value: str | None) -> str | None:
        return value if value and value.strip() else None

    @model_validator(mode="after")
    def _unique_tools(self) -> "AgentConfig":
        keys = [tool.tool_key for tool in self.tools]
        if len(keys) != len(set(keys)):
            raise ValueError("each tool can be assigned only once")
        return self


AgentName = Annotated[str, Field(min_length=2, max_length=200)]


def _clean_name(value: str) -> str:
    value = value.strip()
    if len(value) < 2:
        raise ValueError("name must be at least 2 characters")
    return value


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AgentName
    description: str | None = Field(default=None, max_length=2_000)
    config: AgentConfig

    _name = field_validator("name")(_clean_name)


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AgentName | None = None
    description: str | None = Field(default=None, max_length=2_000)
    status: Literal["active", "disabled"] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)

    @model_validator(mode="after")
    def _something_to_change(self) -> "AgentUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        return self


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: AgentConfig
    change_note: str | None = Field(default=None, max_length=500)


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class DuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AgentName | None = None


class ToolAssignmentRead(BaseModel):
    tool_key: str
    name: str
    description: str
    is_sensitive: bool
    requires_approval: bool
    config: dict[str, Any]


class VersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    provider: LLMProvider
    model: str
    change_note: str | None
    created_by_id: uuid.UUID | None
    created_at: datetime


class VersionRead(VersionSummary):
    system_instructions: str
    objectives: str | None
    model_params: dict[str, Any]
    memory_config: dict[str, Any]
    limits: dict[str, Any]
    tools: list[ToolAssignmentRead]


class AgentListItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    current_version: VersionSummary | None


class AgentRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    current_version: VersionRead | None


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    description: str
    input_schema: dict[str, Any]
    is_sensitive: bool
    timeout_seconds: int
