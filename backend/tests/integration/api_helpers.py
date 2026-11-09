import uuid
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import Engine, text

from app.core.auth_server import AuthServerUser
from app.core.errors import ApiError
from tests.auth_helpers import make_token


class FakeAuthServer:
    """Stands in for Supabase's Auth server. Every email is confirmed unless a test says otherwise."""

    def __init__(self) -> None:
        self.unconfirmed: set[str] = set()
        self.reports_other_email: dict[str, str] = {}
        self.down = False
        self.calls = 0

    async def get_user(self, access_token: str) -> AuthServerUser:
        self.calls += 1
        if self.down:
            raise ApiError(503, "auth_unavailable", "Authentication is temporarily unavailable.")
        claims = jwt.decode(access_token, options={"verify_signature": False})
        email = str(claims["email"]).lower()
        return AuthServerUser(
            id=uuid.UUID(claims["sub"]),
            email=self.reports_other_email.get(email, email),
            email_confirmed=email not in self.unconfirmed,
        )


class Api:
    """Drives the real API as different users, against a real database."""

    def __init__(
        self, client: httpx.AsyncClient, key: ec.EllipticCurvePrivateKey, owner: Engine
    ) -> None:
        self.client = client
        self.key = key
        self.owner = owner
        self.auth_server = FakeAuthServer()

    @staticmethod
    def user_id(email: str) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_DNS, email)

    def token(self, email: str) -> str:
        return make_token(self.key, user_id=self.user_id(email), email=email)

    async def request(self, email: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token(email)}"}
        return await self.client.request(method, path, headers=headers, **kwargs)

    async def get(self, email: str, path: str, **kw: Any) -> httpx.Response:
        return await self.request(email, "GET", path, **kw)

    async def post(self, email: str, path: str, **kw: Any) -> httpx.Response:
        return await self.request(email, "POST", path, **kw)

    async def patch(self, email: str, path: str, **kw: Any) -> httpx.Response:
        return await self.request(email, "PATCH", path, **kw)

    async def delete(self, email: str, path: str, **kw: Any) -> httpx.Response:
        return await self.request(email, "DELETE", path, **kw)

    async def create_org(
        self, email: str, name: str = "Acme Inc", slug: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if slug:
            body["slug"] = slug
        response = await self.post(email, "/api/v1/organizations", json=body)
        assert response.status_code == 201, response.text
        return dict(response.json())

    async def add_member(self, org_id: str, email: str, role: str) -> None:
        """Test setup shortcut: sign the user in (creating their profile) and add a membership."""
        assert (await self.get(email, "/api/v1/auth/me")).status_code == 200
        with self.owner.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO organization_members (org_id, user_id, role) VALUES (:o, :u, :r)"
                ),
                {"o": org_id, "u": self.user_id(email), "r": role},
            )

    def scalar(self, sql: str, **params: object) -> Any:
        with self.owner.connect() as conn:
            return conn.execute(text(sql), params).scalar_one()

    def execute(self, sql: str, **params: object) -> None:
        with self.owner.begin() as conn:
            conn.execute(text(sql), params)
