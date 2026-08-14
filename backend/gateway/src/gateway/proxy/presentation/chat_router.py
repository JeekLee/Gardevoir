"""The OpenAI-compatible chat completions route.

Thin: it reads the contract headers, delegates to the services, and frames the
response. No infrastructure imports (skills/gardevoir-be).
"""

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from gateway.contract import API_PREFIX, HEADER_GUARDRAIL, HEADER_MODE, HEADER_REQUEST_ID
from gateway.identity.composition import AuthenticationServiceDep
from gateway.identity.domain.api_key import Scope
from gateway.proxy.application.proxy_service import wants_stream
from gateway.proxy.composition import ProxyServiceDep

router = APIRouter(prefix=API_PREFIX)


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    auth_service: AuthenticationServiceDep,
    proxy: ProxyServiceDep,
) -> Response:
    auth = await auth_service.authenticate(
        authorization=request.headers.get("authorization"),
        guardrail=request.headers.get(HEADER_GUARDRAIL),
        mode=request.headers.get(HEADER_MODE),
        require=Scope.PROXY,
    )
    payload = await request.body()
    request_id = request.headers.get(HEADER_REQUEST_ID, "")

    if wants_stream(payload):
        return await _stream(proxy, auth=auth, payload=payload, request_id=request_id)

    result = await proxy.complete(auth=auth, payload=payload, request_id=request_id)
    return Response(
        content=result.body,
        status_code=result.status_code,
        media_type=result.media_type,
        headers=result.headers,
    )


async def _stream(proxy, *, auth, payload: bytes, request_id: str) -> StreamingResponse:
    """Relay SSE.

    응답 헤더는 본문보다 먼저 나가므로 스트림을 열어 status 를 확정한 뒤
    StreamingResponse 를 만든다. 컨텍스트 매니저를 본문 제너레이터가 끝날 때까지
    살려둬야 하므로 __aenter__/__aexit__ 를 직접 다룬다 — 라우트가 반환한 뒤에
    Starlette 가 본문을 소비하기 때문이다.
    """
    cm = proxy.stream(auth=auth, payload=payload, request_id=request_id)
    stream = await cm.__aenter__()

    async def body():
        try:
            async for chunk in stream.aiter():
                yield chunk
        finally:
            # 여기서 나가면서 감사가 기록되고 업스트림 연결이 닫힌다.
            await cm.__aexit__(None, None, None)

    return StreamingResponse(
        body(),
        status_code=stream.status_code,
        media_type=stream.media_type,
        headers=stream.headers,
    )
