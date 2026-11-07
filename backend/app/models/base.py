import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, ForeignKeyConstraint, MetaData, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantMixin:
    """Every tenant-owned table carries org_id. Row Level Security keys off this column."""

    @declared_attr
    def org_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            index=True,
        )


def enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    """String column with a CHECK constraint (easier to migrate than native PG enums)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


def tenant_fk(column: str, parent: str, *, ondelete: str | None = None) -> ForeignKeyConstraint:
    """Composite FK (child_col, org_id) -> parent(id, org_id).

    Guarantees a child row can only reference a parent in the SAME organization,
    so a bug can never link data across tenants. The parent table must declare
    UniqueConstraint("id", "org_id").
    """
    return ForeignKeyConstraint(
        [column, "org_id"],
        [f"{parent}.id", f"{parent}.org_id"],
        ondelete=ondelete,
    )


def json_object() -> MappedColumn[Any]:
    return mapped_column(JSONB, server_default=text("'{}'::jsonb"))


def json_array() -> MappedColumn[Any]:
    return mapped_column(JSONB, server_default=text("'[]'::jsonb"))


def now_column() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def nullable_timestamp() -> MappedColumn[datetime | None]:
    return mapped_column(DateTime(timezone=True))
