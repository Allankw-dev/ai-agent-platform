"""Structural rules for secrets, checked by reading the source.

Only one service decrypts a credential, only repositories touch the encrypted column, and no
response schema has a field that could carry a secret.
"""

import re
from pathlib import Path

from app.schemas.integration import IntegrationRead

APP = Path(__file__).resolve().parents[1] / "app"


def _python_files() -> list[Path]:
    return [path for path in APP.rglob("*.py") if "__pycache__" not in path.parts]


def test_only_the_credentials_service_decrypts() -> None:
    allowed = {APP / "core" / "vault.py", APP / "services" / "credentials.py"}
    offenders = [
        path.relative_to(APP).as_posix()
        for path in _python_files()
        if re.search(r"\.decrypt\(", path.read_text()) and path not in allowed
    ]
    assert offenders == []


def test_only_the_model_and_repository_touch_the_encrypted_column() -> None:
    allowed = {
        APP / "models" / "integrations.py",
        APP / "repositories" / "credentials.py",
        APP / "services" / "credentials.py",
    }
    offenders = [
        path.relative_to(APP).as_posix()
        for path in _python_files()
        if "encrypted_payload" in path.read_text() and path not in allowed
    ]
    assert offenders == []


def test_the_credentials_service_is_only_used_by_the_integrations_service_and_tool_access() -> None:
    users = {
        path.relative_to(APP).as_posix()
        for path in _python_files()
        if re.search(r"services\.credentials|services import credentials", path.read_text())
    }
    # Saving/removing a secret (the integrations service) and handing it to a running tool call
    # (tools/integration_access.py) are the only two legitimate uses.
    assert users <= {"services/integrations.py", "tools/integration_access.py"}


def test_no_response_model_has_a_field_for_the_secret() -> None:
    names = set(IntegrationRead.model_fields)
    assert not {name for name in names if re.search(r"secret|token|password|payload", name)}


def test_only_tool_access_and_the_credentials_service_read_a_secret() -> None:
    """`reveal_secret` is the one function that returns a plaintext secret."""
    callers = {
        path.relative_to(APP).as_posix()
        for path in _python_files()
        if "reveal_secret" in path.read_text()
    }
    assert callers == {"services/credentials.py", "tools/integration_access.py"}


def test_the_http_tool_never_logs() -> None:
    """The tool handles secrets, so it must not print or log anything itself."""
    source = (APP / "tools" / "http.py").read_text()
    assert "log." not in source and "logging" not in source and "print(" not in source
