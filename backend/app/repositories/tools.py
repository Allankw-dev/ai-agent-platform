from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Tool


async def list_all(session: AsyncSession) -> list[Tool]:
    return list(await session.scalars(select(Tool).order_by(Tool.key)))


async def by_keys(session: AsyncSession, keys: list[str]) -> dict[str, Tool]:
    if not keys:
        return {}
    rows = await session.scalars(select(Tool).where(Tool.key.in_(keys)))
    return {tool.key: tool for tool in rows}
