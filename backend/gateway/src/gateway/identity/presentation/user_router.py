"""사용자. 경로는 자원을 가리키고, 권한은 라우트마다 붙는다."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from gateway.identity.application.access_token import AccessTokenClaims
from gateway.identity.application.user_command import (
    ChangePassword,
    ChangeRole,
    CreateUser,
    UpdateUser,
)
from gateway.identity.application.user_result import UserSummary
from gateway.identity.application.user_service import UserService
from gateway.identity.composition import current_claims, provide_user_service, require_role
from gateway.identity.domain.enums.role import Role
from shared_kernel.api import JsonResponse, Page

router = APIRouter(prefix="/users", tags=["users"], default_response_class=JsonResponse)

UserServiceDep = Annotated[UserService, Depends(provide_user_service)]
CurrentClaims = Annotated[AccessTokenClaims, Depends(current_claims)]
AdminClaims = Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))]


@router.get("/me")
async def me(claims: CurrentClaims, service: UserServiceDep) -> UserSummary:
    return await service.get(claims.user_id)


@router.put("/me")
async def update_me(
    body: UpdateUser, claims: CurrentClaims, service: UserServiceDep
) -> UserSummary:
    return await service.update(claims.user_id, body)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    body: ChangePassword, claims: CurrentClaims, service: UserServiceDep
) -> None:
    """성공하면 이 사용자의 세션이 전부 끊긴다 — 다시 로그인해야 한다."""
    await service.change_password(claims.user_id, body)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(body: CreateUser, _: AdminClaims, service: UserServiceDep) -> UserSummary:
    return await service.create(body)


@router.get("")
async def list_users(_: AdminClaims, service: UserServiceDep) -> Page[UserSummary]:
    return await service.list()


@router.post("/{user_id}/role")
async def change_role(
    user_id: UUID, body: ChangeRole, _: AdminClaims, service: UserServiceDep
) -> UserSummary:
    return await service.change_role(user_id, body)


@router.post("/{user_id}/deactivate")
async def deactivate_user(user_id: UUID, _: AdminClaims, service: UserServiceDep) -> UserSummary:
    return await service.deactivate(user_id)
