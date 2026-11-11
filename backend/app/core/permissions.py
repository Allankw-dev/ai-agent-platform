"""Role-based access control within an organization.

Roles form a hierarchy: owner > admin > developer > member. The API enforces roles; the database
separately enforces that nobody can reach another organization's data.
"""

import enum

from app.models.enums import OrgRole

ROLE_RANK: dict[OrgRole, int] = {
    OrgRole.OWNER: 4,
    OrgRole.ADMIN: 3,
    OrgRole.DEVELOPER: 2,
    OrgRole.MEMBER: 1,
}


class Permission(enum.StrEnum):
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    MEMBERS_VIEW = "members:view"
    MEMBERS_MANAGE = "members:manage"  # invite, change roles, remove, list invitations
    AGENTS_VIEW = "agents:view"
    AGENTS_MANAGE = "agents:manage"  # create, edit, version, roll back, duplicate, enable, delete
    RUNS_VIEW = "runs:view"
    RUNS_CREATE = "runs:create"  # start and cancel runs


_ALL = frozenset(OrgRole)

GRANTS: dict[Permission, frozenset[OrgRole]] = {
    Permission.ORG_UPDATE: frozenset({OrgRole.OWNER, OrgRole.ADMIN}),
    Permission.ORG_DELETE: frozenset({OrgRole.OWNER}),
    Permission.MEMBERS_VIEW: _ALL,
    Permission.MEMBERS_MANAGE: frozenset({OrgRole.OWNER, OrgRole.ADMIN}),
    Permission.AGENTS_VIEW: _ALL,
    Permission.AGENTS_MANAGE: frozenset({OrgRole.OWNER, OrgRole.ADMIN, OrgRole.DEVELOPER}),
    Permission.RUNS_VIEW: _ALL,
    Permission.RUNS_CREATE: frozenset({OrgRole.OWNER, OrgRole.ADMIN, OrgRole.DEVELOPER}),
}


def has_permission(role: OrgRole, permission: Permission) -> bool:
    return role in GRANTS[permission]


def can_manage(actor: OrgRole, target: OrgRole) -> bool:
    """May `actor` change or remove someone currently holding `target`?"""
    return actor is OrgRole.OWNER or ROLE_RANK[actor] > ROLE_RANK[target]


def can_assign(actor: OrgRole, new_role: OrgRole) -> bool:
    """May `actor` hand out `new_role`? Only owners can create peers or superiors."""
    return actor is OrgRole.OWNER or ROLE_RANK[new_role] < ROLE_RANK[actor]
