from fastapi import APIRouter

from app.api.deps import ConfirmedUser, SessionDep
from app.schemas.organization import InvitationAccept, InvitationAccepted, OrganizationRead
from app.services import invitations as invitation_service

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/accept", response_model=InvitationAccepted)
async def accept_invitation(
    body: InvitationAccept, user: ConfirmedUser, session: SessionDep
) -> InvitationAccepted:
    """Join an organization with an invitation token.

    The signed-in email must match the invitation and must be confirmed with the Auth server.
    """
    organization, role = await invitation_service.accept_invitation(session, user, body.token)
    return InvitationAccepted(organization=OrganizationRead.model_validate(organization), role=role)
