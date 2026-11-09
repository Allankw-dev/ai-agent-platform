"""Asks Supabase's Auth server about a user. Used where an email address grants access.

An access token's `email` claim only says which address the account was created with. Whether that
address was ever confirmed is recorded as `email_confirmed_at` on the user, which only the Auth
server can vouch for (the token has no such claim). Anything that trusts "this person owns this
address" therefore asks here, so it stays safe even if email confirmation is switched off.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from app.core.errors import ApiError

log = structlog.get_logger()


@dataclass(frozen=True)
class AuthServerUser:
    id: uuid.UUID
    email: str
    email_confirmed: bool


class AuthServer(Protocol):
    async def get_user(self, access_token: str) -> AuthServerUser: ...


def _unavailable() -> ApiError:
    return ApiError(503, "auth_unavailable", "Authentication is temporarily unavailable.")


class SupabaseAuthServer:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/auth/v1/user"
        self._api_key = api_key
        self._transport = transport
        self._timeout = timeout

    async def get_user(self, access_token: str) -> AuthServerUser:
        headers = {"apikey": self._api_key, "Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.get(self._url, headers=headers)
        except httpx.HTTPError as exc:
            log.error("auth_server.unreachable", error=type(exc).__name__)
            raise _unavailable() from exc

        if response.status_code in (401, 403):
            raise ApiError(
                401,
                "invalid_token",
                "The access token is invalid or has expired.",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        if response.status_code != 200:
            log.error("auth_server.unexpected_status", status=response.status_code)
            raise _unavailable()

        try:
            body = response.json()
            return AuthServerUser(
                id=uuid.UUID(str(body["id"])),
                email=str(body["email"]).strip().lower(),
                # Only the email's own confirmation counts, not a confirmed phone number.
                email_confirmed=bool(body.get("email_confirmed_at")),
            )
        except (ValueError, KeyError, TypeError) as exc:
            log.error("auth_server.malformed_response")
            raise _unavailable() from exc
