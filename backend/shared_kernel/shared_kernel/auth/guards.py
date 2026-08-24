"""FastAPI 인가 가드. 모든 컨텍스트의 라우터가 공유한다.

의존성이어야 한다 — 핸들러 본문에 두면 FastAPI 가 그 전에 요청 본문을 검증하므로, 권한 없는
호출자가 403 대신 422 로 스키마를 알아낸다.

검증기는 ``request.app.state.access_tokens`` 에서 온다 (조립 루트가 심는다). 가드는
``AccessTokenVerifier`` 만 알고 서명 능력은 모른다.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from shared_kernel.auth.claims import AccessTokenClaims
from shared_kernel.auth.codec import AccessTokenCodec
from shared_kernel.auth.errors import AuthError
from shared_kernel.auth.role import Role


def provide_codec(request: Request) -> AccessTokenCodec:
    return request.app.state.access_tokens


def current_claims(
    request: Request,
    codec: Annotated[AccessTokenCodec, Depends(provide_codec)],
) -> AccessTokenClaims:
    """액세스 토큰을 검증해 클레임을 돌려준다. DB 를 읽지 않는다."""
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        AuthError.INVALID_TOKEN.raise_()
    return codec.decode(token)


def require_role(role: Role) -> Callable[..., AccessTokenClaims]:
    def guard(
        claims: Annotated[AccessTokenClaims, Depends(current_claims)],
    ) -> AccessTokenClaims:
        if claims.role is not role:
            AuthError.ROLE_REQUIRED.raise_(
                details={"required": str(role), "actual": str(claims.role)}
            )
        return claims

    return guard


__all__ = ["current_claims", "provide_codec", "require_role"]
