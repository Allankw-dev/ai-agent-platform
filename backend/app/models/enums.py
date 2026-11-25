import enum


class OrgRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    MEMBER = "member"


class AgentStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class IntegrationProvider(enum.StrEnum):
    GITHUB = "github"
    GMAIL = "gmail"
    SLACK = "slack"
    GOOGLE_CALENDAR = "google_calendar"
    HTTP = "http"
    WEBHOOK = "webhook"


class IntegrationStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class CredentialKind(enum.StrEnum):
    API_KEY = "api_key"
    OAUTH_TOKEN = "oauth_token"  # noqa: S105 (enum label, not a secret)


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunTrigger(enum.StrEnum):
    MANUAL = "manual"
    TEST = "test"
    API = "api"


class StepType(enum.StrEnum):
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    APPROVAL = "approval"
    ERROR = "error"


class StepStatus(enum.StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"  # a tool call waiting for a person to decide
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"  # the run was cancelled or ended before anyone decided


class RunEventType(enum.StrEnum):
    """What changed on a run. Events say that something changed, never what the data was."""

    QUEUED = "run.queued"
    STARTED = "run.started"
    STEP_STARTED = "step.started"
    STEP_FINISHED = "step.finished"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"  # also for expired and cancelled (decided by the system)
    AWAITING_APPROVAL = "run.awaiting_approval"
    RESUMED = "run.resumed"
    FINISHED = "run.finished"  # succeeded or failed (see data.status)
    CANCELLED = "run.cancelled"


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class LLMProvider(enum.StrEnum):
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
