import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.context import OrgContext
from app.api.deps import SessionDep, require
from app.core.permissions import Permission
from app.models.enums import IntegrationProvider
from app.schemas.common import Page
from app.schemas.integration import (
    CredentialSet,
    IntegrationCreate,
    IntegrationRead,
    IntegrationUpdate,
)
from app.services import integrations as integration_service

router = APIRouter(prefix="/organizations/{org_id}/integrations", tags=["integrations"])

CanView = Annotated[OrgContext, Depends(require(Permission.INTEGRATIONS_VIEW))]
CanManage = Annotated[OrgContext, Depends(require(Permission.INTEGRATIONS_MANAGE))]

LimitQuery = Annotated[int, Query(ge=1, le=100)]
OffsetQuery = Annotated[int, Query(ge=0)]


@router.get("", response_model=Page[IntegrationRead])
async def list_integrations(
    ctx: CanView,
    session: SessionDep,
    provider: IntegrationProvider | None = None,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> Page[IntegrationRead]:
    items, total = await integration_service.list_integrations(
        session, ctx, provider=provider, limit=limit, offset=offset
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=IntegrationRead, status_code=201)
async def create_integration(
    body: IntegrationCreate, ctx: CanManage, session: SessionDep
) -> IntegrationRead:
    return await integration_service.create_integration(session, ctx, body)


@router.get("/{integration_id}", response_model=IntegrationRead)
async def get_integration(
    integration_id: uuid.UUID, ctx: CanView, session: SessionDep
) -> IntegrationRead:
    return await integration_service.get_integration(session, ctx, integration_id)


@router.patch("/{integration_id}", response_model=IntegrationRead)
async def update_integration(
    integration_id: uuid.UUID, body: IntegrationUpdate, ctx: CanManage, session: SessionDep
) -> IntegrationRead:
    return await integration_service.update_integration(session, ctx, integration_id, body)


@router.delete("/{integration_id}", status_code=204, response_class=Response)
async def delete_integration(
    integration_id: uuid.UUID, ctx: CanManage, session: SessionDep
) -> Response:
    await integration_service.delete_integration(session, ctx, integration_id)
    return Response(status_code=204)


@router.put("/{integration_id}/credential", response_model=IntegrationRead)
async def put_credential(
    integration_id: uuid.UUID, body: CredentialSet, ctx: CanManage, session: SessionDep
) -> IntegrationRead:
    """Save or replace the integration's secret. Write-only: no endpoint ever returns it."""
    return await integration_service.set_credential(session, ctx, integration_id, body)


@router.delete("/{integration_id}/credential", status_code=204, response_class=Response)
async def delete_credential(
    integration_id: uuid.UUID, ctx: CanManage, session: SessionDep
) -> Response:
    await integration_service.remove_credential(session, ctx, integration_id)
    return Response(status_code=204)
