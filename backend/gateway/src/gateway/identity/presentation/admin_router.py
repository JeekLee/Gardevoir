"""API key management.

⚠️ **아직 사람 인증이 없다.** `admin` 스코프를 가진 키만 요구한다 — 그 키가 새면
**다른 키를 전부 발급·회수할 수 있다.** 정책을 바꾸는 것보다 위험하다. Phase 5(UI)가
관리자 인증(세션/OIDC)을 정할 때 함께 붙이고, 그때까지 이 경로를 외부에 노출하면
안 된다 (설계 문서 §14, infra/README.md).

인가는 라우터 레벨 의존성 하나다. 핸들러마다 반복하면 새 라우트가 빠뜨릴 수 있고,
FastAPI 가 본문을 먼저 검증해서 크레덴셜 없는 호출자가 422 로 스키마를 알아낸다.
"""

from fastapi import APIRouter, status

from gateway.contract import API_PREFIX
from gateway.identity.application.api_key_command import CreateApiKey
from gateway.identity.application.api_key_result import ApiKeyCreated, ApiKeySummary
from gateway.identity.composition import AdminScopeDep, ApiKeyServiceDep
from shared_kernel.api import JsonResponse, Page

ADMIN_PREFIX = f"{API_PREFIX}/admin/api-keys"

router = APIRouter(
    prefix=ADMIN_PREFIX,
    tags=["admin"],
    # 인가는 크레덴셜에서만 온다 (§7.2). 헤더로 관리자가 될 수는 없다.
    dependencies=[AdminScopeDep],
    default_response_class=JsonResponse,
)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_api_key(body: CreateApiKey, service: ApiKeyServiceDep) -> ApiKeyCreated:
    """Create a key.

    **응답의 `key` 가 원본이 보이는 유일한 순간이다.** 저장되는 것은 sha256 해시뿐이라
    잃으면 복구할 수 없고 다시 만들어야 한다 (§7.2).
    """
    return await service.create(body)


@router.get("")
async def list_api_keys(service: ApiKeyServiceDep) -> Page[ApiKeySummary]:
    """List keys. 원본 키도 해시도 업스트림 시크릿도 나가지 않는다."""
    return await service.list()


@router.post("/{key_id}/disable")
async def disable_api_key(key_id: str, service: ApiKeyServiceDep) -> ApiKeySummary:
    """Revoke a key.

    행을 지우지 않는다 — 감사 로그가 `api_key_id` 를 참조하므로, 지우면 과거 기록이
    어느 키의 것인지 알 수 없게 된다 (§10).
    """
    return await service.set_disabled(key_id, disabled=True)


@router.post("/{key_id}/enable")
async def enable_api_key(key_id: str, service: ApiKeyServiceDep) -> ApiKeySummary:
    return await service.set_disabled(key_id, disabled=False)
