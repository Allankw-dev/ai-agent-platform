from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import AuthClaims, TokenVerifier
from app.db.session import get_session
from app.models.identity import User
from app.services import auth as auth_service

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def _build_verifier(supabase_url: str, audience: str) -> TokenVerifier:
    issuer = f"{supabase_url}/auth/v1"
    keys = jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True, timeout=5)
    return TokenVerifier(keys, issuer=issuer, audience=audience)


def get_token_verifier() -> TokenVerifier:
    settings = get_settings()
    if not settings.supabase_url:
        raise ApiError(503, "auth_not_configured", "Authentication is not configured.")
    return _build_verifier(settings.supabase_url.rstrip("/"), settings.supabase_jwt_audience)


def get_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> AuthClaims:
    # Sync on purpose: FastAPI runs it in a worker thread, so fetching the key set
    # never blocks the event loop.
    if credentials is None:
        raise ApiError(
            401,
            "not_authenticated",
            "Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verifier.verify(credentials.credentials)


async def get_current_user(
    claims: Annotated[AuthClaims, Depends(get_claims)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    return await auth_service.get_or_provision_user(session, claims)


CurrentUser = Annotated[User, Depends(get_current_user)]
