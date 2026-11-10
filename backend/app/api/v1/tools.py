from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.repositories import tools as tool_repo
from app.schemas.agent import ToolRead

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolRead])
async def list_tools(_: CurrentUser, session: SessionDep) -> list[ToolRead]:
    """The global catalog of tools an agent can be given. Read-only for everyone."""
    return [ToolRead.model_validate(tool) for tool in await tool_repo.list_all(session)]
