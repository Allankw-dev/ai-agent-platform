import redis.asyncio as redis
import structlog
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_sessionmaker

log = structlog.get_logger()


async def check_database() -> bool:
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        log.exception("health.database_failed")
        return False
    return True


async def check_redis() -> bool:
    client = redis.from_url(get_settings().redis_url)
    try:
        return bool(await client.ping())
    except Exception:
        log.exception("health.redis_failed")
        return False
    finally:
        await client.aclose()
