"""The credential vault: encryption that is bound to its row, and the key handling around it."""

import base64
import uuid

import pytest

from app.core import vault as vault_module
from app.core.config import get_settings
from app.core.vault import (
    NONCE_BYTES,
    REDACTED,
    Vault,
    VaultDecryptError,
    VaultNotConfiguredError,
    generate_key,
    get_vault,
    parse_key,
    redact_secret,
)

ORG = uuid.uuid4()
INTEGRATION = uuid.uuid4()
SECRET = "xoxb-1234567890-the-bot-token"


@pytest.fixture
def vault() -> Vault:
    return Vault(parse_key(generate_key()))


def seal(vault: Vault, secret: str = SECRET) -> tuple[bytes, int]:
    return vault.encrypt(secret, org_id=ORG, integration_id=INTEGRATION)


def test_a_secret_round_trips(vault: Vault) -> None:
    payload, version = seal(vault)
    assert vault.decrypt(payload, version, org_id=ORG, integration_id=INTEGRATION) == SECRET


def test_unicode_secrets_round_trip(vault: Vault) -> None:
    payload, version = seal(vault, "pässwörd-秘密")
    assert (
        vault.decrypt(payload, version, org_id=ORG, integration_id=INTEGRATION) == "pässwörd-秘密"
    )


def test_the_stored_bytes_do_not_contain_the_secret(vault: Vault) -> None:
    payload, _ = seal(vault)
    assert SECRET.encode() not in payload
    assert len(payload) > NONCE_BYTES + len(SECRET)  # nonce + ciphertext + authentication tag


def test_every_encryption_uses_a_fresh_nonce(vault: Vault) -> None:
    first, _ = seal(vault)
    second, _ = seal(vault)
    assert first != second
    assert first[:NONCE_BYTES] != second[:NONCE_BYTES]


def test_a_different_key_cannot_decrypt(vault: Vault) -> None:
    payload, version = seal(vault)
    other = Vault(parse_key(generate_key()))
    with pytest.raises(VaultDecryptError):
        other.decrypt(payload, version, org_id=ORG, integration_id=INTEGRATION)


@pytest.mark.parametrize("position", [0, NONCE_BYTES, -1])
def test_tampered_data_is_rejected(vault: Vault, position: int) -> None:
    payload, version = seal(vault)
    damaged = bytearray(payload)
    damaged[position] ^= 0x01
    with pytest.raises(VaultDecryptError):
        vault.decrypt(bytes(damaged), version, org_id=ORG, integration_id=INTEGRATION)


def test_a_value_moved_to_another_integration_cannot_be_decrypted(vault: Vault) -> None:
    payload, version = seal(vault)
    with pytest.raises(VaultDecryptError):
        vault.decrypt(payload, version, org_id=ORG, integration_id=uuid.uuid4())


def test_a_value_moved_to_another_organization_cannot_be_decrypted(vault: Vault) -> None:
    payload, version = seal(vault)
    with pytest.raises(VaultDecryptError):
        vault.decrypt(payload, version, org_id=uuid.uuid4(), integration_id=INTEGRATION)


def test_an_unknown_key_version_is_rejected(vault: Vault) -> None:
    payload, version = seal(vault)
    with pytest.raises(VaultDecryptError):
        vault.decrypt(payload, version + 1, org_id=ORG, integration_id=INTEGRATION)


@pytest.mark.parametrize("payload", [b"", b"short", b"x" * NONCE_BYTES])
def test_a_truncated_value_is_rejected(vault: Vault, payload: bytes) -> None:
    with pytest.raises(VaultDecryptError):
        vault.decrypt(payload, 1, org_id=ORG, integration_id=INTEGRATION)


def test_errors_never_contain_the_secret(vault: Vault) -> None:
    payload, version = seal(vault)
    with pytest.raises(VaultDecryptError) as caught:
        vault.decrypt(payload, version, org_id=ORG, integration_id=uuid.uuid4())
    assert SECRET not in str(caught.value)


# ---------- the key setting ----------


def test_a_generated_key_is_valid_and_random() -> None:
    first, second = generate_key(), generate_key()
    assert first != second
    assert len(parse_key(first)) == 32


def test_standard_base64_and_whitespace_are_accepted() -> None:
    raw = bytes(range(32))
    assert parse_key(base64.b64encode(raw).decode() + "\n") == raw
    assert parse_key(base64.urlsafe_b64encode(raw).decode()) == raw


@pytest.mark.parametrize(
    "bad", ["", "not base64 at all!!", base64.b64encode(b"too short").decode(), "a" * 3]
)
def test_a_bad_key_is_refused_with_a_clear_message(bad: str) -> None:
    with pytest.raises(VaultNotConfiguredError) as caught:
        parse_key(bad)
    assert "CREDENTIAL_ENCRYPTION_KEY" in str(caught.value)


def test_no_key_means_the_vault_is_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(vault_module, "get_settings", lambda: _Settings(None))
        with pytest.raises(VaultNotConfiguredError, match="CREDENTIAL_ENCRYPTION_KEY"):
            get_vault()
    finally:
        get_settings.cache_clear()


def test_a_configured_key_gives_a_working_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    key = generate_key()
    monkeypatch.setattr(vault_module, "get_settings", lambda: _Settings(key))
    payload, version = get_vault().encrypt(SECRET, org_id=ORG, integration_id=INTEGRATION)
    assert get_vault().decrypt(payload, version, org_id=ORG, integration_id=INTEGRATION) == SECRET


class _Secret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _Settings:
    def __init__(self, key: str | None) -> None:
        self.credential_encryption_key = None if key is None else _Secret(key)


# ---------- redaction ----------


def test_redact_secret_in_strings_and_nested_data() -> None:
    data = {
        "echo": f"Authorization: Bearer {SECRET}",
        "items": [SECRET, {"deep": f"x{SECRET}y"}],
        "count": 3,
        SECRET: "the key itself",
    }
    cleaned = redact_secret(data, SECRET)
    assert SECRET not in repr(cleaned)
    assert cleaned["echo"] == f"Authorization: Bearer {REDACTED}"
    assert cleaned["count"] == 3


def test_redact_secret_with_an_empty_secret_changes_nothing() -> None:
    assert redact_secret("abc", "") == "abc"
