import pytest
from pydantic import ValidationError

from app.models.enums import IntegrationProvider
from app.schemas.integration import (
    MAX_SECRET_CHARS,
    CredentialSet,
    IntegrationCreate,
    IntegrationUpdate,
    normalize_config,
)

HTTP = IntegrationProvider.HTTP
SLACK = IntegrationProvider.SLACK


def test_http_defaults_allow_no_hosts() -> None:
    config = normalize_config(HTTP, {})
    assert config == {"allowed_hosts": [], "auth_header": "Authorization", "auth_scheme": "Bearer"}


def test_hosts_are_cleaned_lowercased_and_deduplicated() -> None:
    config = normalize_config(
        HTTP, {"allowed_hosts": [" API.Example.com ", "api.example.com", "b.example.org."]}
    )
    assert config["allowed_hosts"] == ["api.example.com", "b.example.org"]


@pytest.mark.parametrize(
    "host",
    [
        "https://api.example.com",
        "api.example.com/path",
        "api.example.com:8080",
        "*.example.com",
        "localhost",
        "127.0.0.1",
        "169.254.169.254",
        "-bad.example.com",
        "exa mple.com",
        "",
        "a" * 300 + ".com",
    ],
)
def test_bad_hosts_are_rejected(host: str) -> None:
    with pytest.raises(ValidationError):
        normalize_config(HTTP, {"allowed_hosts": [host]})


def test_too_many_hosts_are_rejected() -> None:
    hosts = [f"h{i}.example.com" for i in range(51)]
    with pytest.raises(ValidationError):
        normalize_config(HTTP, {"allowed_hosts": hosts})


@pytest.mark.parametrize("header", ["Host", "cookie", "Content-Length", "Bad Header", "", "1abc"])
def test_a_credential_cannot_use_a_connection_header(header: str) -> None:
    with pytest.raises(ValidationError):
        normalize_config(HTTP, {"auth_header": header})


def test_a_raw_key_header_is_allowed() -> None:
    config = normalize_config(HTTP, {"auth_header": "X-API-Key", "auth_scheme": ""})
    assert config["auth_header"] == "X-API-Key"
    assert config["auth_scheme"] == ""


def test_unknown_settings_are_rejected() -> None:
    with pytest.raises(ValidationError):
        normalize_config(HTTP, {"allow_everything": True})
    with pytest.raises(ValidationError):
        normalize_config(SLACK, {"allowed_hosts": ["a.example.com"]})


def test_slack_channels_are_checked_and_deduplicated() -> None:
    config = normalize_config(SLACK, {"allowed_channels": ["c0123456789", "C0123456789"]})
    assert config["allowed_channels"] == ["C0123456789"]
    for bad in ["general", "#general", "C1", "U0123456789", ""]:
        with pytest.raises(ValidationError):
            normalize_config(SLACK, {"allowed_channels": [bad]})


def test_other_providers_are_not_available_yet() -> None:
    with pytest.raises(ValueError, match="not available yet"):
        normalize_config(IntegrationProvider.GITHUB, {})


def test_names_are_trimmed_and_need_two_characters() -> None:
    assert IntegrationCreate(provider=HTTP, name="  Weather API ").name == "Weather API"
    with pytest.raises(ValidationError):
        IntegrationCreate(provider=HTTP, name=" a ")


def test_an_update_needs_something_to_change() -> None:
    with pytest.raises(ValidationError):
        IntegrationUpdate()
    assert IntegrationUpdate(status="disabled").status == "disabled"
    with pytest.raises(ValidationError):
        IntegrationUpdate.model_validate({"status": "error"})


def test_a_secret_is_trimmed_and_hidden_in_reprs() -> None:
    body = CredentialSet.model_validate({"secret": "  abc123  \n"})
    assert body.secret.get_secret_value() == "abc123"
    assert "abc123" not in repr(body)
    assert "abc123" not in str(body.model_dump())


def test_empty_and_oversized_secrets_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CredentialSet.model_validate({"secret": "   "})
    with pytest.raises(ValidationError):
        CredentialSet.model_validate({"secret": "x" * (MAX_SECRET_CHARS + 1)})
    with pytest.raises(ValidationError):
        CredentialSet.model_validate({"secret": "abc", "extra": 1})
