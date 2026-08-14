"""Identity 의 요청 수명 배선.

조립 루트는 ``app.py`` 다 — 여기 함수들이 ``Request`` 를 받는 것이 그 증거다.
"""

from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Depends, Request

from gateway.identity.application.access_token import AccessTokenClaims, AccessTokenCodec
from gateway.identity.application.auth_service import AuthService
from gateway.identity.application.bearer import parse_bearer
from gateway.identity.application.user_service import UserService
from gateway.identity.domain.enums.role import Role
from gateway.identity.domain.exceptions.user_error import UserError
from gateway.identity.infrastructure.redis_refresh_session_repository import (
    RedisRefreshSessionRepository,
)
from gateway.identity.infrastructure.user_dao import SqlAlchemyUserDao
from gateway.identity.infrastructure.user_repository import SqlAlchemyUserRepository


def provide_access_token_codec(request: Request) -> AccessTokenCodec:
    return request.app.state.access_tokens


async def provide_auth_service(request: Request) -> AsyncIterator[AuthService]:
    async with request.app.state.session_factory() as session:
        yield AuthService(
            users=SqlAlchemyUserRepository(session),
            dao=SqlAlchemyUserDao(session),
            sessions=RedisRefreshSessionRepository(request.app.state.redis),
            tokens=request.app.state.access_tokens,
            refresh_ttl=request.app.state.refresh_ttl,
            transaction=session,
        )
        await session.commit()


async def provide_user_service(request: Request) -> AsyncIterator[UserService]:
    async with request.app.state.session_factory() as session:
        yield UserService(
            users=SqlAlchemyUserRepository(session),
            dao=SqlAlchemyUserDao(session),
            sessions=RedisRefreshSessionRepository(request.app.state.redis),
            transaction=session,
        )
        await session.commit()


def current_claims(
    request: Request,
    codec: Annotated[AccessTokenCodec, Depends(provide_access_token_codec)],
) -> AccessTokenClaims:
    """액세스 토큰을 검증해 클레임을 돌려준다. DB 를 읽지 않는다."""
    token = parse_bearer(request.headers.get("authorization"))
    if token is None:
        UserError.INVALID_TOKEN.raise_()
    return codec.decode(token)


def require_role(role: Role) -> Callable[..., AccessTokenClaims]:
    """그 역할을 요구하는 의존성을 만든다.

    핸들러 본문이 아니라 의존성이어야 한다. 본문에 두면 FastAPI 가 그 전에 요청 본문을
    검증하므로, 권한 없는 호출자가 403 대신 422 로 스키마를 알아낸다.
    """

    def guard(
        claims: Annotated[AccessTokenClaims, Depends(current_claims)],
    ) -> AccessTokenClaims:
        if claims.role is not role:
            UserError.ROLE_REQUIRED.raise_(
                details={"required": str(role), "actual": str(claims.role)}
            )
        return claims

    return guard
