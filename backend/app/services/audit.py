import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import AuditLog


async def record(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append to the audit log. Runs inside the caller's transaction."""
    await session.execute(
        insert(AuditLog).values(
            org_id=org_id,
            actor_user_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            details=details or {},
        )
    )
