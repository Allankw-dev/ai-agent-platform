"""Verification of Supabase Auth access tokens (JWTs).

Supabase signs tokens with an asymmetric key and publishes the public keys at
<project>/auth/v1/.well-known/jwks.json. We verify signature, issuer, audience and expiry locally.
Only asymmetric algorithms are accepted, which blocks "alg: none" and HS256 key-confusion attacks.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
import structlog

from app.core.errors import ApiError

log = structlog.get_logger()

ALLOWED_ALGORITHMS = ("ES256", "RS256")
CLOCK_SKEW_SECONDS = 10


class SigningKey(Protocol):
    @property
    def key(self) -> Any: ...


class SigningKeyProvider(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> SigningKey: ...


@dataclass(frozen=True)
class AuthClaims:
    user_id: uuid.UUID
    email: str


def _invalid(reason: str) -> ApiError:
    # The reason is logged, never returned: callers only learn that the token was rejected.
    log.info("auth.token_rejected", reason=reason)
    return ApiError(
        401,
        "invalid_token",
        "The access token is invalid or has expired.",
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


class TokenVerifier:
    def __init__(self, keys: SigningKeyProvider, issuer: str, audience: str) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> AuthClaims:
        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as exc:
            raise _invalid("malformed token") from exc
        if algorithm not in ALLOWED_ALGORITHMS:
            raise _invalid(f"algorithm not allowed: {algorithm}")

        try:
            signing_key = self._keys.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWKClientConnectionError as exc:
            log.error("auth.jwks_unreachable", error=str(exc))
            raise ApiError(
                503, "auth_unavailable", "Authentication is temporarily unavailable."
            ) from exc
        except jwt.PyJWTError as exc:
            raise _invalid(f"{type(exc).__name__}: {exc}") from exc

        return self._claims(payload)

    @staticmethod
    def _claims(payload: dict[str, Any]) -> AuthClaims:
        if payload.get("role") != "authenticated":
            raise _invalid("role is not authenticated")
        if payload.get("is_anonymous") is True:
            raise _invalid("anonymous users are not accepted")
        email = payload.get("email")
        if not isinstance(email, str) or not email.strip():
            raise _invalid("token has no email")
        try:
            user_id = uuid.UUID(str(payload["sub"]))
        except ValueError as exc:
            raise _invalid("subject is not a UUID") from exc
        return AuthClaims(user_id=user_id, email=email.strip().lower())
