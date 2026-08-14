"""로그인 · 갱신 · 로그아웃."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from gateway.identity.application.auth_service import AuthService
from gateway.identity.application.user_command import Login, Refresh
from gateway.identity.application.user_result import LoginResult, TokenPair
from gateway.identity.composition import provide_auth_service
from shared_kernel.api import JsonResponse

router = APIRouter(prefix="/auth", tags=["auth"], default_response_class=JsonResponse)


@router.post("/login")
async def login(
    body: Login,
    service: Annotated[AuthService, Depends(provide_auth_service)],
) -> LoginResult:
    return await service.login(body)


@router.post("/refresh")
async def refresh(
    body: Refresh,
    service: Annotated[AuthService, Depends(provide_auth_service)],
) -> TokenPair:
    """갱신할 때마다 리프레시 토큰이 회전한다 — 옛 토큰은 그 즉시 무효다."""
    return await service.refresh(body)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: Refresh,
    service: Annotated[AuthService, Depends(provide_auth_service)],
) -> None:
    """없는 토큰이어도 204 — 무엇이 유효한지 알려주지 않는다."""
    await service.logout(body.refresh_token)
