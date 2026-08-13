"""Guardrail authoring API.

⚠️ **아직 사람 인증이 없다.** 이 라우터는 `admin` 스코프를 가진 API 키만 요구한다.
그 키가 새면 정책 전체를 바꿀 수 있다. Phase 5(UI)가 관리자 인증(세션/OIDC)을
정할 때 함께 붙이고, 그때까지 이 경로를 외부에 노출하면 안 된다 — 설계 문서 §14 와
infra/README.md 에 같은 내용이 있다.

컨트롤 플레인과 데이터 플레인이 한 프로세스에 있는 것은 결정 사항이다(§12).
둘을 가르는 것은 배포 토폴로지가 아니라 경로 접두사와 크레덴셜 스코프다.
"""

from fastapi import APIRouter, Request, status

from gateway.application.command.guardrail_command import CreateGuardrail, UpdateDraft
from gateway.application.result.guardrail_result import GuardrailDetail, GuardrailSummary
from gateway.composition import AuthenticationServiceDep, GuardrailServiceDep
from gateway.contract import API_PREFIX
from gateway.domain.models.api_key import Scope
from shared_kernel.api import JsonResponse, Page

router = APIRouter(
    prefix=f"{API_PREFIX}/admin/guardrails",
    tags=["admin"],
    default_response_class=JsonResponse,
)


async def _authorise(request: Request, auth_service: AuthenticationServiceDep) -> None:
    """인가는 크레덴셜에서만 온다 (§7.2). 헤더로 관리자가 될 수는 없다.

    가드레일을 해석하지 않는다 — 저작 API 에는 해석할 가드레일이 없다.
    """
    await auth_service.authorise(
        authorization=request.headers.get("authorization"),
        require=Scope.ADMIN,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_guardrail(
    request: Request,
    body: CreateGuardrail,
    auth_service: AuthenticationServiceDep,
    service: GuardrailServiceDep,
) -> GuardrailDetail:
    await _authorise(request, auth_service)
    return await service.create(body)


@router.get("")
async def list_guardrails(
    request: Request,
    auth_service: AuthenticationServiceDep,
    service: GuardrailServiceDep,
) -> Page[GuardrailSummary]:
    await _authorise(request, auth_service)
    return await service.list()


@router.get("/{name}")
async def get_guardrail(
    request: Request,
    name: str,
    auth_service: AuthenticationServiceDep,
    service: GuardrailServiceDep,
) -> GuardrailDetail:
    """The newest published version — what the proxy would actually run."""
    await _authorise(request, auth_service)
    return await service.get_latest(name)


@router.get("/{name}/draft")
async def get_draft(
    request: Request,
    name: str,
    auth_service: AuthenticationServiceDep,
    service: GuardrailServiceDep,
) -> GuardrailDetail:
    await _authorise(request, auth_service)
    return await service.get_draft(name)


@router.put("/{name}/draft")
async def put_draft(
    request: Request,
    name: str,
    body: UpdateDraft,
    auth_service: AuthenticationServiceDep,
    service: GuardrailServiceDep,
) -> GuardrailDetail:
    await _authorise(request, auth_service)
    return await service.update_draft(name, body)


@router.post("/{name}/publish")
async def publish_guardrail(
    request: Request,
    name: str,
    auth_service: AuthenticationServiceDep,
    service: GuardrailServiceDep,
) -> GuardrailDetail:
    await _authorise(request, auth_service)
    return await service.publish(name)


@router.get("/{name}/versions/{version_number}")
async def get_version(
    request: Request,
    name: str,
    version_number: int,
    auth_service: AuthenticationServiceDep,
    service: GuardrailServiceDep,
) -> GuardrailDetail:
    await _authorise(request, auth_service)
    return await service.get_version(name, version_number)
