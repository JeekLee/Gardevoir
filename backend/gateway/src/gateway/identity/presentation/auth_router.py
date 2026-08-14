"""로그인 · 갱신 · 로그아웃."""

from fastapi import APIRouter, status

from gateway.identity.application.user_command import Login, Refresh
from gateway.identity.application.user_result import LoginResult, TokenPair
from gateway.identity.composition import AuthServiceDep
from shared_kernel.api import JsonResponse

router = APIRouter(prefix="/auth", tags=["auth"], default_response_class=JsonResponse)


@router.post("/login")
async def login(body: Login, service: AuthServiceDep) -> LoginResult:
    return await service.login(body)


@router.post("/refresh")
async def refresh(body: Refresh, service: AuthServiceDep) -> TokenPair:
    """갱신할 때마다 리프레시 토큰이 회전한다 — 옛 토큰은 그 즉시 무효다."""
    return await service.refresh(body)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: Refresh, service: AuthServiceDep) -> None:
    """세션을 회수한다. 없는 토큰이어도 204 — 무엇이 유효한지 알려주지 않는다."""
    await service.logout(body.refresh_token)
