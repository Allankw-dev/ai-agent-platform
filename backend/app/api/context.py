import uuid
from dataclasses import dataclass

from app.models.enums import OrgRole
from app.models.identity import User


@dataclass(frozen=True)
class OrgContext:
    """The authenticated user acting within one organization, with their role there."""

    user: User
    org_id: uuid.UUID
    role: OrgRole
