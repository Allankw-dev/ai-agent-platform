"""Encryption for stored secrets (the credential vault).

Secrets are encrypted with AES-256-GCM (the `cryptography` library). The key is 32 random bytes in
the CREDENTIAL_ENCRYPTION_KEY setting (base64 text), never in git. What is stored is the 12-byte
nonce followed by the ciphertext and its authentication tag, with a `key_version` kept beside it so
a new key can be introduced later.

The organization and integration ids are mixed into the encryption as "associated data". A stored
value copied onto another integration row, or into another organization, therefore fails to
decrypt, and so does any tampered byte.

Generate a key with:  docker compose exec api python -m app.core.vault

Only `app/services/credentials.py` calls `decrypt` (a test enforces this).
"""

import base64
import binascii
import os
import secrets
import uuid
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

KEY_BYTES = 32
NONCE_BYTES = 12
CURRENT_KEY_VERSION = 1
REDACTED = "[redacted]"


class VaultError(Exception):
    """A vault failure. The message is safe to show to users and never contains a secret."""


class VaultNotConfiguredError(VaultError):
    """There is no usable CREDENTIAL_ENCRYPTION_KEY, so secrets can be neither saved nor used."""


class VaultDecryptError(VaultError):
    """The stored value could not be decrypted (wrong key, moved to another row, or tampered)."""


def generate_key() -> str:
    """A new random key, as base64 text for the CREDENTIAL_ENCRYPTION_KEY setting."""
    return base64.urlsafe_b64encode(secrets.token_bytes(KEY_BYTES)).decode("ascii")


def parse_key(raw: str) -> bytes:
    """Decode the setting's base64 text into 32 key bytes."""
    text = raw.strip()
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise VaultNotConfiguredError(
            "CREDENTIAL_ENCRYPTION_KEY is not valid base64 text. Generate a new one with "
            "'docker compose exec api python -m app.core.vault'."
        ) from exc
    if len(decoded) != KEY_BYTES:
        raise VaultNotConfiguredError(
            f"CREDENTIAL_ENCRYPTION_KEY must decode to exactly {KEY_BYTES} bytes. Generate a new "
            "one with 'docker compose exec api python -m app.core.vault'."
        )
    return decoded


def _associated_data(org_id: uuid.UUID, integration_id: uuid.UUID, key_version: int) -> bytes:
    return f"credential:v{key_version}:{org_id}:{integration_id}".encode("ascii")


class Vault:
    def __init__(self, key: bytes, *, key_version: int = CURRENT_KEY_VERSION) -> None:
        if len(key) != KEY_BYTES:
            raise VaultNotConfiguredError("The encryption key has the wrong length.")
        self._aead = AESGCM(key)
        self.key_version = key_version

    def encrypt(
        self, secret: str, *, org_id: uuid.UUID, integration_id: uuid.UUID
    ) -> tuple[bytes, int]:
        """Returns (nonce + ciphertext + tag, key_version). A fresh random nonce every time."""
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(
            nonce,
            secret.encode("utf-8"),
            _associated_data(org_id, integration_id, self.key_version),
        )
        return nonce + sealed, self.key_version

    def decrypt(
        self,
        payload: bytes,
        key_version: int,
        *,
        org_id: uuid.UUID,
        integration_id: uuid.UUID,
    ) -> str:
        if key_version != self.key_version:
            raise VaultDecryptError("The stored credential uses an unknown key version.")
        if len(payload) <= NONCE_BYTES:
            raise VaultDecryptError("The stored credential could not be decrypted.")
        nonce, sealed = payload[:NONCE_BYTES], payload[NONCE_BYTES:]
        try:
            plain = self._aead.decrypt(
                nonce, sealed, _associated_data(org_id, integration_id, key_version)
            )
        except InvalidTag as exc:
            raise VaultDecryptError("The stored credential could not be decrypted.") from exc
        return plain.decode("utf-8")


def get_vault() -> Vault:
    """The vault for this server's key, or VaultNotConfiguredError if there is none."""
    key = get_settings().credential_encryption_key
    if key is None or not key.get_secret_value().strip():
        raise VaultNotConfiguredError(
            "Saving and using credentials needs CREDENTIAL_ENCRYPTION_KEY to be set on the "
            "server. Generate one with 'docker compose exec api python -m app.core.vault'."
        )
    return Vault(parse_key(key.get_secret_value()))


def redact_secret(value: Any, secret: str) -> Any:
    """Replace every occurrence of `secret` in a string, or anywhere inside nested dicts/lists.

    Used on a tool's output before it is recorded or shown to the model, in case the remote
    service echoed the credential back.
    """
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, REDACTED)
    if isinstance(value, dict):
        return {
            redact_secret(key, secret) if isinstance(key, str) else key: redact_secret(item, secret)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact_secret(item, secret) for item in value]
    return value


if __name__ == "__main__":  # pragma: no cover - a one-line key generator for the setup steps
    print(generate_key())
