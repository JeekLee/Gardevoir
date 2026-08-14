"""Identity 의 요청 수명 배선.

조립 루트는 ``app.py`` 다 — 여기 함수들이 ``Request`` 를 받는 것이 그 증거다.
``presentation/`` 이 아닌 이유: 자기 컨텍스트의 ``SqlAlchemy*`` 를 임포트해야 한다.
"""

from collections.abc import AsyncIterator
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


AuthServiceDep = Annotated[AuthService, Depends(provide_auth_service)]
UserServiceDep = Annotated[UserService, Depends(provide_user_service)]
AccessTokenCodecDep = Annotated[AccessTokenCodec, Depends(provide_access_token_codec)]


def current_claims(request: Request, codec: AccessTokenCodecDep) -> AccessTokenClaims:
    """액세스 토큰을 검증해 클레임을 돌려준다. DB 를 읽지 않는다.

    역할이 토큰 안에 있으므로 역할 변경은 토큰이 갱신될 때 반영된다. 즉시 끊어야 하는
    경우는 세션 회수(``revoke_all_for_user``)가 담당한다.
    """
    token = parse_bearer(request.headers.get("authorization"))
    if token is None:
        UserError.INVALID_TOKEN.raise_()
    return codec.decode(token)


CurrentClaimsDep = Annotated[AccessTokenClaims, Depends(current_claims)]


def require_admin_claims(claims: CurrentClaimsDep) -> AccessTokenClaims:
    if claims.role is not Role.ADMIN:
        UserError.NOT_ADMIN.raise_(details={"role": str(claims.role)})
    return claims


AdminClaimsDep = Annotated[AccessTokenClaims, Depends(require_admin_claims)]

#: 라우터의 ``dependencies=`` 에 넣는다.
AdminOnly = Depends(require_admin_claims)
