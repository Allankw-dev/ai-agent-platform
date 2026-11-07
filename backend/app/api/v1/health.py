from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.health import check_database, check_redis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def liveness() -> dict[str, str]:
    """Process is up. Does not touch dependencies."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness(
    database_ok: Annotated[bool, Depends(check_database)],
    redis_ok: Annotated[bool, Depends(check_redis)],
) -> JSONResponse:
    """Dependencies are reachable. Returns 503 if any check fails."""
    checks = {"database": database_ok, "redis": redis_ok}
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "unavailable", "checks": checks},
    )
