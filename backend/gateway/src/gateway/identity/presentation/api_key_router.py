"""API 키. 로그인 사용자가 자기 키를 관리한다 — user_id 로 소유가 정해진다."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from gateway.identity.application.command.api_key_command import CreateApiKey, UpdateApiKey
from gateway.identity.application.result.api_key_result import ApiKeyCreated, ApiKeySummary
from gateway.identity.application.service.api_key_service import ApiKeyService
from gateway.identity.composition import provide_api_key_service
from shared_kernel.api import JsonResponse, Page
from shared_kernel.auth import AccessTokenClaims, current_claims

router = APIRouter(prefix="/api-keys", tags=["api-keys"], default_response_class=JsonResponse)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: CreateApiKey,
    claims: Annotated[AccessTokenClaims, Depends(current_claims)],
    service: Annotated[ApiKeyService, Depends(provide_api_key_service)],
) -> ApiKeyCreated:
    """발급. 원본 키는 이 응답에만 실린다."""
    return await service.create(claims.user_id, body)


@router.get("")
async def list_api_keys(
    claims: Annotated[AccessTokenClaims, Depends(current_claims)],
    service: Annotated[ApiKeyService, Depends(provide_api_key_service)],
) -> Page[ApiKeySummary]:
    return await service.list(claims.user_id)


@router.put("/{api_key_id}")
async def update_api_key(
    api_key_id: UUID,
    body: UpdateApiKey,
    claims: Annotated[AccessTokenClaims, Depends(current_claims)],
    service: Annotated[ApiKeyService, Depends(provide_api_key_service)],
) -> ApiKeySummary:
    return await service.update(claims.user_id, api_key_id, body)


@router.post("/{api_key_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(current_claims)],
    service: Annotated[ApiKeyService, Depends(provide_api_key_service)],
) -> None:
    """멱등 — 이미 회수된 키를 다시 회수해도 204."""
    await service.revoke(claims.user_id, api_key_id)
