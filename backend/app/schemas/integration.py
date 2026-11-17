"""Request and response shapes for integrations (connected external accounts).

An integration holds non-secret settings (`config`). Its secret is saved separately and is
write-only: no response in this module has a field that could carry it.
"""

import ipaddress
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.models.enums import IntegrationProvider

# Integrations that can be created today. The others exist in the data model for later phases.
SUPPORTED_PROVIDERS = frozenset({IntegrationProvider.HTTP, IntegrationProvider.SLACK})

MAX_HOSTS = 50
MAX_CHANNELS = 50
MAX_SECRET_CHARS = 4_096

_HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME = re.compile(rf"^(?=.{{1,253}}$){_HOST_LABEL}(?:\.{_HOST_LABEL})+$")
_HEADER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
_AUTH_SCHEME = re.compile(r"^[A-Za-z0-9-]{0,32}$")
_SLACK_CHANNEL = re.compile(r"^[CG][A-Z0-9]{8,20}$")
# Headers the integration may not use for its credential: they control the connection itself.
_FORBIDDEN_HEADERS = frozenset(
    {
        "host",
        "cookie",
        "set-cookie",
        "content-length",
        "content-type",
        "transfer-encoding",
        "connection",
        "upgrade",
        "te",
        "trailer",
        "expect",
        "proxy-authorization",
    }
)


class HttpConfig(BaseModel):
    """Settings for the HTTP tools. An empty host list means the agent may call nothing."""

    model_config = ConfigDict(extra="forbid")

    # Exact host names an agent may call through this integration (no wildcards, ports or paths).
    allowed_hosts: list[str] = Field(default_factory=list, max_length=MAX_HOSTS)
    # How the saved secret is sent: "<auth_header>: <auth_scheme> <secret>". An empty scheme
    # sends the secret alone (for example `X-API-Key: <secret>`).
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"

    @field_validator("allowed_hosts")
    @classmethod
    def _hosts(cls, hosts: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in hosts:
            host = raw.strip().lower().rstrip(".")
            if not _HOSTNAME.match(host):
                raise ValueError(
                    f"{raw.strip()[:60]!r} is not a valid host name. Use a name like "
                    "api.example.com, without https://, a port or a path."
                )
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError("Use a host name, not an IP address.")
            if host not in cleaned:
                cleaned.append(host)
        return cleaned

    @field_validator("auth_header")
    @classmethod
    def _header(cls, value: str) -> str:
        value = value.strip()
        if not _HEADER_NAME.match(value):
            raise ValueError("auth_header must be a plain header name such as Authorization.")
        if value.lower() in _FORBIDDEN_HEADERS:
            raise ValueError(f"{value} cannot be used to carry a credential.")
        return value

    @field_validator("auth_scheme")
    @classmethod
    def _scheme(cls, value: str) -> str:
        value = value.strip()
        if not _AUTH_SCHEME.match(value):
            raise ValueError("auth_scheme may only contain letters, digits and hyphens.")
        return value


class SlackConfig(BaseModel):
    """Settings for Slack. A message to a channel not listed here is refused."""

    model_config = ConfigDict(extra="forbid")

    allowed_channels: list[str] = Field(default_factory=list, max_length=MAX_CHANNELS)

    @field_validator("allowed_channels")
    @classmethod
    def _channels(cls, channels: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in channels:
            channel = raw.strip().upper()
            if not _SLACK_CHANNEL.match(channel):
                raise ValueError(
                    f"{raw.strip()[:30]!r} is not a Slack channel id. Channel ids look like "
                    "C0123456789 (open the channel's details in Slack to find it)."
                )
            if channel not in cleaned:
                cleaned.append(channel)
        return cleaned


def normalize_config(provider: IntegrationProvider, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate `raw` for the provider and return the cleaned settings to store.

    Raises ValueError (with a message that is safe to show) when something is wrong.
    """
    if provider is IntegrationProvider.HTTP:
        return HttpConfig.model_validate(raw).model_dump()
    if provider is IntegrationProvider.SLACK:
        return SlackConfig.model_validate(raw).model_dump()
    raise ValueError(f"The {provider.value} integration is not available yet.")


IntegrationName = Annotated[str, Field(min_length=2, max_length=200)]


def _clean_name(value: str) -> str:
    value = value.strip()
    if len(value) < 2:
        raise ValueError("name must be at least 2 characters")
    return value


class IntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: IntegrationProvider
    name: IntegrationName
    config: dict[str, Any] = Field(default_factory=dict)

    _name = field_validator("name")(_clean_name)


class IntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: IntegrationName | None = None
    status: Literal["active", "disabled"] | None = None
    config: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)

    @model_validator(mode="after")
    def _something_to_change(self) -> "IntegrationUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        return self


class CredentialSet(BaseModel):
    """The secret to save (an API key or bot token). Write-only: nothing ever returns it."""

    model_config = ConfigDict(extra="forbid")

    secret: SecretStr

    @field_validator("secret")
    @classmethod
    def _secret_shape(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value().strip()
        if not text:
            raise ValueError("The secret cannot be empty.")
        if len(text) > MAX_SECRET_CHARS:
            raise ValueError(f"The secret is longer than {MAX_SECRET_CHARS} characters.")
        return SecretStr(text)


class IntegrationRead(BaseModel):
    """An integration as the API shows it. There is deliberately no field for the secret itself:
    only whether one is saved, by whom, and when."""

    id: uuid.UUID
    provider: IntegrationProvider
    name: str
    status: str
    config: dict[str, Any]
    has_credential: bool
    credential_set_by_id: uuid.UUID | None
    credential_set_by_name: str | None
    credential_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime
