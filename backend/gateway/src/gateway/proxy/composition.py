"""Proxy 의 요청 수명 배선.

조립 루트는 ``app.py`` 다 — identity/composition.py 의 설명과 같다.
"""

from typing import Annotated

from fastapi import Depends, Request

from gateway.guardrail.inspection.application.service.inspector import Inspector
from gateway.proxy.application.service.proxy_service import ProxyService


def provide_proxy_service(request: Request) -> ProxyService:
    return ProxyService(
        upstream=request.app.state.upstream,
        audit=request.app.state.audit_sink,
        # 계획 레지스트리는 프로세스 수명이므로 app.state 가 소유한다. 검사기는
        # 상태가 없어 요청마다 만들어도 된다.
        inspector=Inspector(plans=request.app.state.plans),
        holdback_chars=request.app.state.settings.stream_holdback_chars,
        window_chars=request.app.state.settings.stream_window_chars,
    )


ProxyServiceDep = Annotated[ProxyService, Depends(provide_proxy_service)]
