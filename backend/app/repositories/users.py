import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User


async def get(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def insert_if_absent(session: AsyncSession, user_id: uuid.UUID, email: str) -> None:
    """Race-safe: two simultaneous first requests create exactly one row."""
    statement = (
        insert(User)
        .values(id=user_id, email=email)
        .on_conflict_do_nothing(index_elements=[User.id])
    )
    await session.execute(statement)
