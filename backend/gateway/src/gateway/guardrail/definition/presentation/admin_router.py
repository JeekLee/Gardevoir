"""Guardrail authoring API.

⚠️ **아직 사람 인증이 없다.** 이 라우터는 `admin` 스코프를 가진 API 키만 요구한다.
그 키가 새면 정책 전체를 바꿀 수 있다. Phase 5(UI)가 관리자 인증(세션/OIDC)을
정할 때 함께 붙이고, 그때까지 이 경로를 외부에 노출하면 안 된다 — 설계 문서 §14 와
infra/README.md 에 같은 내용이 있다. OpenAPI 스펙도 debug 에서만 열린다(app.py).

인가는 라우터 레벨 의존성 하나다. 핸들러마다 반복하면 새 라우트가 빠뜨릴 수 있고,
FastAPI 가 본문을 먼저 검증해서 크레덴셜 없는 호출자가 422 로 스키마를 알아낸다.

컨트롤 플레인과 데이터 플레인이 한 프로세스에 있는 것은 결정 사항이다(§12).
둘을 가르는 것은 배포 토폴로지가 아니라 경로 접두사와 크레덴셜 스코프다.
"""

from fastapi import APIRouter, status

from gateway.composition import AdminScopeDep, GuardrailServiceDep
from gateway.contract import API_PREFIX
from gateway.guardrail.definition.application.guardrail_command import CreateGuardrail, UpdateDraft
from gateway.guardrail.definition.application.guardrail_result import (
    GuardrailDetail,
    GuardrailSummary,
)
from shared_kernel.api import JsonResponse, Page

ADMIN_PREFIX = f"{API_PREFIX}/admin/guardrails"

router = APIRouter(
    prefix=ADMIN_PREFIX,
    tags=["admin"],
    # 인가는 크레덴셜에서만 온다 (§7.2). 헤더로 관리자가 될 수는 없다.
    dependencies=[AdminScopeDep],
    default_response_class=JsonResponse,
)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_guardrail(body: CreateGuardrail, service: GuardrailServiceDep) -> GuardrailDetail:
    return await service.create(body)


@router.get("")
async def list_guardrails(service: GuardrailServiceDep) -> Page[GuardrailSummary]:
    return await service.list()


@router.get("/{name}")
async def get_guardrail(name: str, service: GuardrailServiceDep) -> GuardrailDetail:
    """The newest published version — what the proxy would actually run."""
    return await service.get_latest(name)


@router.get("/{name}/draft")
async def get_draft(name: str, service: GuardrailServiceDep) -> GuardrailDetail:
    return await service.get_draft(name)


@router.put("/{name}/draft")
async def put_draft(name: str, body: UpdateDraft, service: GuardrailServiceDep) -> GuardrailDetail:
    return await service.update_draft(name, body)


@router.post("/{name}/publish")
async def publish_guardrail(name: str, service: GuardrailServiceDep) -> GuardrailDetail:
    return await service.publish(name)


@router.get("/{name}/versions/{version_number}")
async def get_version(
    name: str, version_number: int, service: GuardrailServiceDep
) -> GuardrailDetail:
    return await service.get_version(name, version_number)
