"""Proxy 의 요청 수명 배선. 조립 루트는 app.py 다."""

from collections.abc import AsyncIterator

from fastapi import Request

from gateway.guardrail.application.service.inspector import (
    CHECKPOINT_INPUT,
    CHECKPOINT_OUTPUT,
    CHECKPOINT_TOOL_CALL,
    CHECKPOINT_TOOL_RESULT,
    Inspector,
)
from gateway.guardrail.application.service.model_tier import FailMode, ModelTier
from gateway.guardrail.infrastructure.dao.guardrail_dao import SqlAlchemyGuardrailDao
from gateway.proxy.application.service.guardrail_test_service import GuardrailTestService
from gateway.proxy.application.service.proxy_service import ProxyService


def provide_model_tier(request: Request) -> ModelTier | None:
    settings = request.app.state.settings.model_judge
    if not settings.enabled:
        return None
    model = settings.model if not settings.revision else f"{settings.model}@{settings.revision}"
    return ModelTier(
        model_judge=request.app.state.model_judge,
        model=model,
        deadline_ms=settings.timeout_ms,
        fail_modes={
            CHECKPOINT_INPUT: FailMode(settings.fail_mode.input),
            CHECKPOINT_TOOL_RESULT: FailMode(settings.fail_mode.tool_result),
            CHECKPOINT_OUTPUT: FailMode(settings.fail_mode.output),
            CHECKPOINT_TOOL_CALL: FailMode(settings.fail_mode.tool_call),
        },
    )


def provide_proxy_service(request: Request) -> ProxyService:
    return ProxyService(
        upstream=request.app.state.upstream,
        upstream_resolver=request.app.state.upstream_resolver,
        audit=request.app.state.audit_sink,
        model_tier=provide_model_tier(request),
        store_bodies=request.app.state.settings.audit.store_bodies,
        audit_excerpt_max_chars=request.app.state.settings.audit.excerpt_max_chars,
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
