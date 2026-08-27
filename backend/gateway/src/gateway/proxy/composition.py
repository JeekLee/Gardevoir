"""Proxy 의 요청 수명 배선. 조립 루트는 app.py 다."""

from collections.abc import AsyncIterator

from fastapi import Request

from gateway.guardrail.application.service.inspector import Inspector
from gateway.guardrail.infrastructure.dao.guardrail_dao import SqlAlchemyGuardrailDao
from gateway.proxy.application.service.guardrail_test_service import GuardrailTestService
from gateway.proxy.application.service.proxy_service import ProxyService


def provide_proxy_service(request: Request) -> ProxyService:
    return ProxyService(
        upstream=request.app.state.upstream,
        upstream_resolver=request.app.state.upstream_resolver,
        audit=request.app.state.audit_sink,
        # 계획 레지스트리는 프로세스 수명이므로 app.state 가 소유한다. 검사기는
        # 상태가 없어 요청마다 만들어도 된다.
        inspector=Inspector(plans=request.app.state.plans),
        holdback_chars=request.app.state.settings.stream_holdback_chars,
        window_chars=request.app.state.settings.stream_window_chars,
    )


async def provide_guardrail_test_service(
    request: Request,
) -> AsyncIterator[GuardrailTestService]:
    async with request.app.state.session_factory() as session:
        yield GuardrailTestService(
            guardrail_dao=SqlAlchemyGuardrailDao(session),
            proxy_service=provide_proxy_service(request),
        )
