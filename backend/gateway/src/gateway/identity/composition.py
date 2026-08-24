"""Identity 의 요청 수명 배선.

조립 루트는 ``app.py`` 다 — 여기 함수들이 ``Request`` 를 받는 것이 그 증거다.

인가 가드(current_claims·require_role)와 검증기는 shared_kernel.auth 에 있다 — 인가는
크로스컷팅이고 서버가 쪼개져도 하류가 필요로 하기 때문이다. 여기는 발급측(identity 전용)만
배선한다.
"""

from collections.abc import AsyncIterator

from fastapi import Request

from gateway.identity.application.service.auth_service import AuthService
from gateway.identity.application.service.user_service import UserService
from gateway.identity.infrastructure.redis_refresh_session_repository import (
    RedisRefreshSessionRepository,
)
from gateway.identity.infrastructure.user_dao import SqlAlchemyUserDao
from gateway.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from shared_kernel.database import SqlAlchemyUnitOfWork


async def provide_auth_service(request: Request) -> AsyncIterator[AuthService]:
    async with request.app.state.session_factory() as session:
        yield AuthService(
            user_repository=SqlAlchemyUserRepository(session),
            user_dao=SqlAlchemyUserDao(session),
            refresh_session_repository=RedisRefreshSessionRepository(request.app.state.redis),
            access_token_issuer=request.app.state.access_tokens,
            refresh_ttl=request.app.state.refresh_ttl,
            unit_of_work=SqlAlchemyUnitOfWork(session),
        )


async def provide_user_service(request: Request) -> AsyncIterator[UserService]:
    async with request.app.state.session_factory() as session:
        yield UserService(
            user_repository=SqlAlchemyUserRepository(session),
            user_dao=SqlAlchemyUserDao(session),
            refresh_session_repository=RedisRefreshSessionRepository(request.app.state.redis),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        )
