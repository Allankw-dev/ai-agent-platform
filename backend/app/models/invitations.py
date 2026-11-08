import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    TenantMixin,
    UUIDPrimaryKeyMixin,
    enum_column,
    now_column,
    nullable_timestamp,
)
from app.models.enums import OrgRole


class OrganizationInvitation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Invitation to join an organization. Only a hash of the one-time token is stored."""

    __tablename__ = "organization_invitations"

    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[OrgRole] = mapped_column(enum_column(OrgRole, "role"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = nullable_timestamp()
    revoked_at: Mapped[datetime | None] = nullable_timestamp()
    created_at: Mapped[datetime] = now_column()

    __table_args__ = (
        # Ownership is granted by promotion, never by invitation.
        CheckConstraint("role <> 'owner'", name="not_owner"),
        # At most one open invitation per email per organization.
        Index(
            "uq_organization_invitations_pending",
            "org_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )
