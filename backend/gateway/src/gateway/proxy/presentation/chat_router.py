"""The OpenAI-compatible chat completions route.

Thin: it reads the contract headers, delegates to the services, and frames the
response. No infrastructure imports (skills/gardevoir-be).
"""

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from gateway.guardrail.domain.models.mode import Mode
from gateway.identity.composition import AuthenticationServiceDep
from gateway.identity.domain.models.api_key import Scope
from gateway.proxy.application.service.proxy_service import wants_stream
from gateway.proxy.composition import ProxyServiceDep
from gateway.proxy.contract import HEADER_GUARDRAIL, HEADER_MODE, HEADER_REQUEST_ID

router = APIRouter()


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    auth_service: AuthenticationServiceDep,
    proxy: ProxyServiceDep,
) -> Response:
    auth = await auth_service.authenticate(
        authorization=request.headers.get("authorization"),
        guardrail=request.headers.get(HEADER_GUARDRAIL),
        require=Scope.PROXY,
    )
    # 모드는 권한 검사 없이 자유 선택이다. 공격자는 대화 텍스트만 통제하고 HTTP 헤더는
    # 만지지 못하므로 dry-run 이 자유여도 도움이 되지 않는다. 남는 리스크는 거버넌스이고,
    # 그것은 감사 로그에 모드를 남겨 드러낸다.
    mode = Mode.parse(request.headers.get(HEADER_MODE))
    payload = await request.body()
    request_id = request.headers.get(HEADER_REQUEST_ID, "")

    if wants_stream(payload):
        return await _stream(proxy, auth=auth, mode=mode, payload=payload, request_id=request_id)

    result = await proxy.complete(auth=auth, mode=mode, payload=payload, request_id=request_id)
    return Response(
        content=result.body,
        status_code=result.status_code,
        media_type=result.media_type,
        headers=result.headers,
    )


async def _stream(proxy, *, auth, mode, payload: bytes, request_id: str) -> StreamingResponse:
    """Relay SSE.

    응답 헤더는 본문보다 먼저 나가므로 스트림을 열어 status 를 확정한 뒤
    StreamingResponse 를 만든다. 컨텍스트 매니저를 본문 제너레이터가 끝날 때까지
    살려둬야 하므로 __aenter__/__aexit__ 를 직접 다룬다 — 라우트가 반환한 뒤에
    Starlette 가 본문을 소비하기 때문이다.
    """
    cm = proxy.stream(auth=auth, mode=mode, payload=payload, request_id=request_id)
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
