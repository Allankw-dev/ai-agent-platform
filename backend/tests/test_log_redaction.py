"""Log lines never carry the value of a field named like a secret."""

import json

import pytest
import structlog

from app.core.logging import REDACTED, configure_logging, redact_sensitive

SECRET = "xoxb-1234567890-the-bot-token"


@pytest.mark.parametrize(
    "field",
    ["token", "access_token", "secret", "client_secret", "Authorization", "password", "api_key"],
)
def test_sensitive_field_names_are_hidden(field: str) -> None:
    cleaned = redact_sensitive(None, "info", {"event": "x", field: SECRET, "run_id": "r1"})
    assert cleaned[field] == REDACTED
    assert cleaned["run_id"] == "r1"
    assert SECRET not in repr(cleaned)


def test_nested_values_are_hidden_too() -> None:
    event = {"event": "x", "headers": {"Authorization": f"Bearer {SECRET}", "Accept": "json"}}
    cleaned = redact_sensitive(None, "info", event)
    assert cleaned["headers"] == {"Authorization": REDACTED, "Accept": "json"}


def test_the_configured_logger_does_not_print_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("info", json_logs=True)
    try:
        structlog.get_logger().info("credential.check", token=SECRET, org_id="o1")
        output = capsys.readouterr().out
    finally:
        structlog.reset_defaults()
    assert SECRET not in output
    line = json.loads(output.strip().splitlines()[-1])
    assert line["token"] == REDACTED
    assert line["org_id"] == "o1"
