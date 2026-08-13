"""Composition root.

인프라 구현체와 fastapi.Depends 를 임포트하는 유일한 곳이다. presentation 은
여기서 서비스만 가져간다 (skills/gardevoir-be).
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request

from gateway.application.service.authentication_service import AuthenticationService
from gateway.application.service.guardrail_service import GuardrailService
from gateway.application.service.proxy_service import ProxyService
from gateway.infrastructure.dao.guardrail_dao import SqlAlchemyGuardrailDao
from gateway.infrastructure.repository.guardrail_repository import SqlAlchemyGuardrailRepository


def provide_authentication_service(request: Request) -> AuthenticationService:
    # 캐시 리포지토리는 프로세스 수명 동안 유지되어야 하므로 app.state 가 소유한다.
    return AuthenticationService(keys=request.app.state.key_cache)


def provide_proxy_service(request: Request) -> ProxyService:
    return ProxyService(
        upstream=request.app.state.upstream,
        audit=request.app.state.audit_sink,
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
        )
        await session.commit()


AuthenticationServiceDep = Annotated[AuthenticationService, Depends(provide_authentication_service)]
ProxyServiceDep = Annotated[ProxyService, Depends(provide_proxy_service)]
GuardrailServiceDep = Annotated[GuardrailService, Depends(provide_guardrail_service)]
