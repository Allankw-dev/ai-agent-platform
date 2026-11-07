import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import OrgRole


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Local profile. The id matches the Supabase Auth user id."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    is_super_admin: Mapped[bool] = mapped_column(server_default=text("false"))


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]*$'", name="slug_format"),)


class OrganizationMember(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "organization_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[OrgRole] = mapped_column(enum_column(OrgRole, "role"))

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_organization_members_org_id_user_id"),
    )
