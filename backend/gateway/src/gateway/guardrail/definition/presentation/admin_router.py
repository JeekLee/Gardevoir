"""Guardrail authoring API.

관리자 사용자의 액세스 토큰을 요구한다. 인가는 라우터 레벨 의존성 하나다 — 핸들러마다
반복하면 새 라우트가 빠뜨릴 수 있고, FastAPI 가 본문을 먼저 검증해서 크레덴셜 없는
호출자가 401 대신 422 로 스키마를 알아낸다.

컨트롤 플레인과 데이터 플레인이 한 프로세스에 있는 것은 결정 사항이다(§12).
둘을 가르는 것은 배포 토폴로지가 아니라 경로 접두사와 크레덴셜 스코프다.
"""

from fastapi import APIRouter, status

from gateway.guardrail.composition import GuardrailServiceDep
from gateway.guardrail.definition.application.guardrail_command import CreateGuardrail, UpdateDraft
from gateway.guardrail.definition.application.guardrail_result import (
    GuardrailDetail,
    GuardrailSummary,
)
from gateway.identity.composition import AdminOnly
from shared_kernel.api import JsonResponse, Page

router = APIRouter(
    prefix="/admin/guardrails",
    tags=["admin"],
    # 인가는 크레덴셜에서만 온다 (§7.2). 헤더로 관리자가 될 수는 없다.
    dependencies=[AdminOnly],
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
