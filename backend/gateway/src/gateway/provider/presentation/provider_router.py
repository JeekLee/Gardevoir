"""업스트림 프로바이더. 관리자만 관리한다 (Role.ADMIN)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from gateway.provider.application.command.provider_command import CreateProvider, UpdateProvider
from gateway.provider.application.result.provider_result import ProviderSummary
from gateway.provider.application.service.provider_service import ProviderService
from gateway.provider.composition import provide_provider_service
from shared_kernel.api import JsonResponse, Page
from shared_kernel.auth import AccessTokenClaims, Role, require_role

router = APIRouter(prefix="/providers", tags=["providers"], default_response_class=JsonResponse)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: CreateProvider,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[ProviderService, Depends(provide_provider_service)],
) -> ProviderSummary:
    return await service.create(body)


@router.get("")
async def list_providers(
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[ProviderService, Depends(provide_provider_service)],
) -> Page[ProviderSummary]:
    return await service.list()


@router.put("/{provider_id}")
async def update_provider(
    provider_id: UUID,
    body: UpdateProvider,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[ProviderService, Depends(provide_provider_service)],
) -> ProviderSummary:
    return await service.update(provider_id, body)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: UUID,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[ProviderService, Depends(provide_provider_service)],
) -> None:
    await service.delete(provider_id)
