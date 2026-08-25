"""Guardrail test API."""

from typing import Annotated

import orjson
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

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


@router.post("/{name}/test/stream")
async def stream_guardrail_test(
    name: str,
    body: TestGuardrail,
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    service: Annotated[
        GuardrailTestService,
        Depends(provide_guardrail_test_service, scope="function"),
    ],
) -> StreamingResponse:
    cm = service.stream(name, body)
    stream = await cm.__aenter__()

    async def chunks():
        try:
            async for chunk in stream.aiter():
                yield chunk
            if stream.status_code < 400:
                payload = stream.result().model_dump(mode="json", by_alias=True)
                yield b"event: result\ndata: " + orjson.dumps(payload) + b"\n\n"
        finally:
            await cm.__aexit__(None, None, None)

    return StreamingResponse(
        chunks(),
        status_code=stream.status_code,
        media_type=stream.media_type,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
