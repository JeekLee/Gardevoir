"""Guardrail test API."""

from typing import Annotated

from fastapi import APIRouter, Depends

from gateway.proxy.application.command.guardrail_test_command import TestGuardrail
from gateway.proxy.application.result.guardrail_test_result import GuardrailTestResult
from gateway.proxy.application.service.guardrail_test_service import GuardrailTestService
from gateway.proxy.composition import provide_guardrail_test_service
from shared_kernel.api import JsonResponse
from shared_kernel.auth import AccessTokenClaims, Role, require_role

router = APIRouter(prefix="/guardrails", tags=["guardrails"], default_response_class=JsonResponse)


@router.post("/{name}/test")
async def test_guardrail(
    name: str,
    body: TestGuardrail,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[GuardrailTestService, Depends(provide_guardrail_test_service)],
) -> GuardrailTestResult:
    return await service.test(name, body)
