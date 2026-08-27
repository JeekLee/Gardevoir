"""Guardrail authoring API.

경로에 ``admin`` 을 넣지 않는다 — 인가는 자원의 성질이 아니라 호출자의 성질이므로 URL 에
담을 것이 아니다. 컨트롤 플레인과 데이터 플레인이 한 프로세스에 있는 것은 결정 사항이고(§12),
둘을 가르는 것은 배포 토폴로지가 아니라 크레덴셜이다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from gateway.guardrail.composition import provide_guardrail_service
from gateway.guardrail.definition.application.command.guardrail_command import (
    CreateGuardrail,
    UpdateDraft,
)
from gateway.guardrail.definition.application.result.guardrail_result import (
    GuardrailDetail,
    GuardrailSummary,
)
from gateway.guardrail.definition.application.service.guardrail_service import GuardrailService
from shared_kernel.api import JsonResponse, Page
from shared_kernel.auth import AccessTokenClaims, Role, require_role

router = APIRouter(prefix="/guardrails", tags=["guardrails"], default_response_class=JsonResponse)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_guardrail(
    body: CreateGuardrail,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailService, Depends(provide_guardrail_service)],
) -> GuardrailDetail:
    return await service.create(body)


@router.get("")
async def list_guardrails(
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailService, Depends(provide_guardrail_service)],
) -> Page[GuardrailSummary]:
    return await service.list()


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_guardrail(
    name: str,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailService, Depends(provide_guardrail_service)],
) -> None:
    await service.delete(name)


@router.get("/{name}")
async def get_guardrail(
    name: str,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailService, Depends(provide_guardrail_service)],
) -> GuardrailDetail:
    """The newest published version — what the proxy would actually run."""
    return await service.get_latest(name)


@router.get("/{name}/draft")
async def get_draft(
    name: str,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailService, Depends(provide_guardrail_service)],
) -> GuardrailDetail:
    return await service.get_draft(name)


@router.put("/{name}/draft")
async def put_draft(
    name: str,
    body: UpdateDraft,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailService, Depends(provide_guardrail_service)],
) -> GuardrailDetail:
    return await service.update_draft(name, body)


@router.post("/{name}/publish")
async def publish_guardrail(
    name: str,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailService, Depends(provide_guardrail_service)],
) -> GuardrailDetail:
    return await service.publish(name)


@router.get("/{name}/versions/{version_number}")
async def get_version(
    name: str,
    version_number: int,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailService, Depends(provide_guardrail_service)],
) -> GuardrailDetail:
    return await service.get_version(name, version_number)
