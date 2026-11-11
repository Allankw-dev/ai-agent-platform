"""Per-transaction tenant context for Row Level Security.

Every transaction that touches tenant data must run with `app.user_id` / `app.org_id` set.
They are set with set_config(..., is_local=true), so they vanish when the transaction ends and
can never leak to the next request that reuses the pooled connection. Because a session starts a
new transaction after every commit, the context is re-applied automatically on each begin.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

INFO_KEY = "tenant_context"

_SET_CONTEXT = text(
    "SELECT set_config('app.user_id', :user_id, true), "
    "set_config('app.org_id', :org_id, true), "
    "set_config('app.invite_hash', :invite_hash, true)"
)


@dataclass(frozen=True)
class TenantContext:
    user_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None
    # SHA-256 of an invitation token. Lets the holder of the token (and only them) look the
    # invitation up before they belong to the organization.
    invite_hash: str | None = None

    def params(self) -> dict[str, str]:
        # An empty string means "unset"; the SQL helper functions map it to NULL.
        return {
            "user_id": str(self.user_id) if self.user_id else "",
            "org_id": str(self.org_id) if self.org_id else "",
            "invite_hash": self.invite_hash or "",
        }


@event.listens_for(Session, "after_begin")
def _apply_context_on_begin(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    context = session.info.get(INFO_KEY)
    if context is not None:
        connection.execute(_SET_CONTEXT, context.params())


async def use_tenant(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    invite_hash: str | None = None,
) -> None:
    """Set the tenant context now and for every later transaction of this session."""
    context = TenantContext(user_id=user_id, org_id=org_id, invite_hash=invite_hash)
    session.sync_session.info[INFO_KEY] = context
    await session.execute(_SET_CONTEXT, context.params())
