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
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"
