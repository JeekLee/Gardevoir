"""Composition root.

인프라 구현체와 fastapi.Depends 를 임포트하는 유일한 곳이다. presentation 은
여기서 서비스만 가져간다 (skills/gardevoir-be).
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request

from gateway.application.inspection.inspector import Inspector
from gateway.application.service.authentication_service import AuthenticationService
from gateway.application.service.guardrail_service import GuardrailService
from gateway.application.service.proxy_service import ProxyService
from gateway.domain.models.api_key import Scope
from gateway.infrastructure.dao.guardrail_dao import SqlAlchemyGuardrailDao
from gateway.infrastructure.repository.guardrail_repository import SqlAlchemyGuardrailRepository

logger = logging.getLogger(__name__)


def provide_authentication_service(request: Request) -> AuthenticationService:
    # 캐시 리포지토리는 프로세스 수명 동안 유지되어야 하므로 app.state 가 소유한다.
    return AuthenticationService(keys=request.app.state.key_cache)


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


async def provide_guardrail_service(request: Request) -> AsyncIterator[GuardrailService]:
    """One session per request, committed only on the success path.

    라우트가 예외를 올리면 FastAPI 가 그 예외를 이 제너레이터의 yield 지점으로
    다시 던지므로 commit 에 도달하지 않고, async with 가 세션을 닫으면서 롤백된다.
    저작 API 는 요청 경로가 아니므로 요청마다 세션을 열어도 된다 (§6 은 프록시
    경로에만 적용된다).
    """
    async with request.app.state.session_factory() as session:
        yield GuardrailService(
            guardrails=SqlAlchemyGuardrailRepository(session),
            dao=SqlAlchemyGuardrailDao(session),
            # 발행은 커밋과 재컴파일 시점을 스스로 알아야 한다 — 조립 루트의 정리
            # 코드에 맡기면 FastAPI 가 응답을 보낸 뒤에 돌려서 발행 직후의 요청이
            # 이전 계획을 본다. application/port/transaction.py 참조.
            transaction=session,
            plans=getattr(request.app.state, "plans", None),
        )
        # 서비스가 자기 쓰기를 이미 커밋했다. 여기서는 남은 것을 정리한다 —
        # 읽기 전용 라우트의 트랜잭션을 닫고, 실패한 요청은 async with 가 롤백한다.
        await session.commit()


AuthenticationServiceDep = Annotated[AuthenticationService, Depends(provide_authentication_service)]
ProxyServiceDep = Annotated[ProxyService, Depends(provide_proxy_service)]
GuardrailServiceDep = Annotated[GuardrailService, Depends(provide_guardrail_service)]


async def require_admin_scope(request: Request, auth_service: AuthenticationServiceDep) -> None:
    """Demand the admin scope before a handler runs.

    라우터 레벨 의존성이어야 한다. 핸들러 첫 줄에 두면 FastAPI 가 그 전에 본문을
    검증하므로, 크레덴셜이 없는 호출자가 401 대신 422 를 받고 스키마를 알아낸다.
    라우트마다 반복하는 한 줄이 아니라 라우터에 한 번 걸어야 새 라우트가 빠뜨릴
    수도 없다.

    가드레일을 해석하지 않는다 — 저작 API 에는 해석할 가드레일이 없다.
    """
    await auth_service.authorise(
        authorization=request.headers.get("authorization"), require=Scope.ADMIN
    )


#: 라우터의 dependencies= 에 넣는다. Depends 는 composition 밖으로 나가지 않는다.
AdminScopeDep = Depends(require_admin_scope)
