"""The application-side helper that sets the tenant context on every transaction."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.tenancy import use_tenant


async def test_context_survives_commits(runtime_url: str) -> None:
    user, org = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(runtime_url)
    try:
        async with async_sessionmaker(engine)() as session:
            await use_tenant(session, user_id=user, org_id=org)
            await session.commit()  # ends the transaction; the next one must get the context again
            row = (
                await session.execute(
                    text(
                        "SELECT current_setting('app.user_id', true), current_setting('app.org_id', true)"
                    )
                )
            ).one()
            assert (row[0], row[1]) == (str(user), str(org))
    finally:
        await engine.dispose()


async def test_context_is_gone_for_a_fresh_session(runtime_url: str) -> None:
    engine = create_async_engine(runtime_url)
    try:
        async with async_sessionmaker(engine)() as session:
            await use_tenant(session, org_id=uuid.uuid4())
        async with async_sessionmaker(engine)() as other:
            value = (
                await other.execute(text("SELECT current_setting('app.org_id', true)"))
            ).scalar_one()
            assert value in (None, "")
    finally:
        await engine.dispose()
