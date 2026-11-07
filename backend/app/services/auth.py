import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.security import AuthClaims
from app.db.tenancy import use_tenant
from app.models.identity import User
from app.repositories import users

log = structlog.get_logger()

_EMAIL_CONFLICT = ApiError(
    409, "email_conflict", "This email address is already linked to another account."
)


async def get_or_provision_user(session: AsyncSession, claims: AuthClaims) -> User:
    """Return the local profile for an authenticated user, creating it on first sign-in."""
    # Row Level Security: from here on this session acts as the authenticated user.
    await use_tenant(session, user_id=claims.user_id)
    user = await users.get(session, claims.user_id)

    try:
        if user is None:
            await users.insert_if_absent(session, claims.user_id, claims.email)
            await session.commit()
            log.info("auth.user_provisioned", user_id=str(claims.user_id))
        elif user.email != claims.email:
            user.email = claims.email
            await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _EMAIL_CONFLICT from exc

    user = await users.get(session, claims.user_id)
    if user is None:  # pragma: no cover - defensive, the row was just inserted
        raise ApiError(500, "user_not_found", "The user profile could not be loaded.")
    return user
