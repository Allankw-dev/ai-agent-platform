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


def test_the_credentials_service_is_only_used_by_the_integrations_service_and_tools() -> None:
    users = {
        path.relative_to(APP).as_posix()
        for path in _python_files()
        if re.search(r"services\.credentials|services import credentials", path.read_text())
    }
    assert users <= {"services/integrations.py"}


def test_no_response_model_has_a_field_for_the_secret() -> None:
    names = set(IntegrationRead.model_fields)
    assert not {name for name in names if re.search(r"secret|token|password|payload", name)}
