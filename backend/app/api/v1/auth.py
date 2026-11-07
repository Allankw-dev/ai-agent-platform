from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser) -> UserRead:
    """The signed-in user's profile. Creates it on first sign-in."""
    return UserRead.model_validate(user)
