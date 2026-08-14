"""사용자 관리. 생성·역할 변경·비활성화는 관리자만 한다."""

from uuid import UUID

from fastapi import APIRouter, status

from gateway.identity.application.user_command import (
    ChangePassword,
    ChangeRole,
    CreateUser,
    UpdateUser,
)
from gateway.identity.application.user_result import UserSummary
from gateway.identity.composition import (
    AdminOnly,
    CurrentClaimsDep,
    UserServiceDep,
)
from shared_kernel.api import JsonResponse, Page

router = APIRouter(prefix="/users", tags=["users"], default_response_class=JsonResponse)

admin_router = APIRouter(
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[AdminOnly],
    default_response_class=JsonResponse,
)


@router.get("/me")
async def me(claims: CurrentClaimsDep, service: UserServiceDep) -> UserSummary:
    return await service.get(claims.user_id)


@router.put("/me")
async def update_me(
    body: UpdateUser, claims: CurrentClaimsDep, service: UserServiceDep
) -> UserSummary:
    return await service.update(claims.user_id, body)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    body: ChangePassword, claims: CurrentClaimsDep, service: UserServiceDep
) -> None:
    """성공하면 이 사용자의 세션이 전부 끊긴다 — 다시 로그인해야 한다."""
    await service.change_password(claims.user_id, body)


@admin_router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(body: CreateUser, service: UserServiceDep) -> UserSummary:
    return await service.create(body)


@admin_router.get("")
async def list_users(service: UserServiceDep) -> Page[UserSummary]:
    return await service.list()


@admin_router.post("/{user_id}/role")
async def change_role(user_id: UUID, body: ChangeRole, service: UserServiceDep) -> UserSummary:
    return await service.change_role(user_id, body)


@admin_router.post("/{user_id}/deactivate")
async def deactivate_user(user_id: UUID, service: UserServiceDep) -> UserSummary:
    return await service.deactivate(user_id)
