import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import OrgRole

Name = Annotated[str, Field(min_length=2, max_length=100)]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")]


class OrganizationCreate(BaseModel):
    name: Name
    slug: Slug | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("name must be at least 2 characters")
        return value


class OrganizationUpdate(BaseModel):
    name: Name

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("name must be at least 2 characters")
        return value


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrganizationWithRole(OrganizationRead):
    role: OrgRole


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: OrgRole
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    role: OrgRole


class InvitationCreate(BaseModel):
    email: EmailStr
    role: OrgRole = OrgRole.MEMBER

    @field_validator("role")
    @classmethod
    def _not_owner(cls, value: OrgRole) -> OrgRole:
        if value is OrgRole.OWNER:
            raise ValueError("ownership is granted by promoting a member, not by invitation")
        return value


class InvitationRead(BaseModel):
    id: uuid.UUID
    email: str
    role: OrgRole
    status: str  # pending | expired | accepted | revoked
    expires_at: datetime
    created_at: datetime


class InvitationCreated(InvitationRead):
    # The only time the link (and its token) is shown. Only a hash is stored.
    invite_url: str


class InvitationAccept(BaseModel):
    token: Annotated[str, Field(min_length=20, max_length=200)]


class InvitationAccepted(BaseModel):
    organization: OrganizationRead
    role: OrgRole
