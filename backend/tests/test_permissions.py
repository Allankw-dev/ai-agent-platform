import pytest

from app.core.permissions import Permission, can_assign, can_manage, has_permission
from app.models.enums import OrgRole

OWNER, ADMIN, DEVELOPER, MEMBER = OrgRole.OWNER, OrgRole.ADMIN, OrgRole.DEVELOPER, OrgRole.MEMBER


@pytest.mark.parametrize(
    ("permission", "allowed"),
    [
        (Permission.ORG_DELETE, {OWNER}),
        (Permission.ORG_UPDATE, {OWNER, ADMIN}),
        (Permission.MEMBERS_MANAGE, {OWNER, ADMIN}),
        (Permission.MEMBERS_VIEW, {OWNER, ADMIN, DEVELOPER, MEMBER}),
        (Permission.AGENTS_VIEW, {OWNER, ADMIN, DEVELOPER, MEMBER}),
        (Permission.AGENTS_MANAGE, {OWNER, ADMIN, DEVELOPER}),
        (Permission.RUNS_VIEW, {OWNER, ADMIN, DEVELOPER, MEMBER}),
        (Permission.RUNS_CREATE, {OWNER, ADMIN, DEVELOPER}),
    ],
)
def test_permission_matrix(permission: Permission, allowed: set[OrgRole]) -> None:
    for role in OrgRole:
        assert has_permission(role, permission) is (role in allowed), (role, permission)


@pytest.mark.parametrize(
    ("actor", "target", "expected"),
    [
        (OWNER, OWNER, True),
        (OWNER, MEMBER, True),
        (ADMIN, OWNER, False),
        (ADMIN, ADMIN, False),
        (ADMIN, DEVELOPER, True),
        (ADMIN, MEMBER, True),
        (DEVELOPER, MEMBER, True),
        (MEMBER, MEMBER, False),
        (MEMBER, DEVELOPER, False),
    ],
)
def test_can_manage(actor: OrgRole, target: OrgRole, expected: bool) -> None:
    assert can_manage(actor, target) is expected


@pytest.mark.parametrize(
    ("actor", "new_role", "expected"),
    [
        (OWNER, OWNER, True),
        (OWNER, ADMIN, True),
        (ADMIN, OWNER, False),
        (ADMIN, ADMIN, False),
        (ADMIN, DEVELOPER, True),
        (ADMIN, MEMBER, True),
        (DEVELOPER, MEMBER, True),
        (DEVELOPER, DEVELOPER, False),
    ],
)
def test_can_assign(actor: OrgRole, new_role: OrgRole, expected: bool) -> None:
    assert can_assign(actor, new_role) is expected
