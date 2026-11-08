import uuid
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import OrgContext
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.permissions import Permission, has_permission
from app.core.security import AuthClaims, TokenVerifier
from app.db.session import get_session
from app.db.tenancy import use_tenant
from app.models.identity import User
from app.repositories import members as member_repo
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


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_org_context(org_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OrgContext:
    """Resolve {org_id} from the path for the signed-in user.

    This is the single place that decides a user may act within an organization: it checks
    membership, then tells the database which organization the rest of the request is scoped to.
    Non-members get 404 (not 403) so organization ids cannot be probed.
    """
    # Membership is readable with only the user context (see the RLS policies).
    role = await member_repo.get_role(session, org_id, user.id)
    if role is None:
        raise ApiError(404, "organization_not_found", "Organization not found.")
    await use_tenant(session, user_id=user.id, org_id=org_id)
    return OrgContext(user=user, org_id=org_id, role=role)


OrgCtx = Annotated[OrgContext, Depends(get_org_context)]


def require(permission: Permission) -> Callable[[OrgContext], Awaitable[OrgContext]]:
    """Dependency factory: the caller's role in the organization must grant `permission`."""

    async def dependency(ctx: OrgCtx) -> OrgContext:
        if not has_permission(ctx.role, permission):
            raise ApiError(403, "forbidden", "Your role does not allow this action.")
        return ctx

    return dependency
