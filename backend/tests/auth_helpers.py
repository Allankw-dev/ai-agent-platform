"""Helpers that mimic Supabase Auth: an EC signing key, its JWKS, and signed access tokens."""

import time
import uuid
from types import SimpleNamespace
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

ISSUER = "https://abcdefgh.supabase.co/auth/v1"
AUDIENCE = "authenticated"
KID = "test-key-1"


def new_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def jwks_for(private_key: ec.EllipticCurvePrivateKey, kid: str = KID) -> dict[str, Any]:
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "use": "sig", "alg": "ES256"}]}


def make_token(
    private_key: ec.EllipticCurvePrivateKey,
    *,
    user_id: uuid.UUID | None = None,
    email: str | None = "Ada@Example.com",
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_in: int = 3600,
    kid: str = KID,
    algorithm: str = "ES256",
    omit: tuple[str, ...] = (),
    **extra: Any,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id or uuid.uuid4()),
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "role": "authenticated",
        "is_anonymous": False,
        **extra,
    }
    if email is not None:
        payload["email"] = email
    for claim in omit:
        payload.pop(claim, None)
    return jwt.encode(payload, private_key, algorithm=algorithm, headers={"kid": kid})


class StaticKeys:
    """A signing-key provider that always returns one public key (no network)."""

    def __init__(self, private_key: ec.EllipticCurvePrivateKey) -> None:
        self._public = private_key.public_key()

    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        return SimpleNamespace(key=self._public)
