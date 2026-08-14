"""``AccessTokenCodec`` over HS256 JWT.

단일 프로세스가 서명하고 검증하므로 대칭 키다. 비대칭(RS256)은 서명하는 서비스와 검증하는
서비스가 다를 때 값이 있고, §12 는 컨테이너 하나를 못박아 뒀다.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from gateway.identity.application.port.access_token_codec import AccessTokenClaims
from gateway.identity.domain.enums.role import Role
from gateway.identity.domain.exceptions.user_error import UserError

_ALGORITHM = "HS256"
_ISSUER = "gardevoir"


class JwtAccessTokenCodec:
    def __init__(self, *, secret: str, ttl: timedelta) -> None:
        self._secret = secret
        self._ttl = ttl

    @property
    def ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())

    def encode(self, *, user_id: UUID, email: str, role: Role) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": str(user_id),
                "email": email,
                "role": str(role),
                "iss": _ISSUER,
                "iat": int(now.timestamp()),
                "exp": int((now + self._ttl).timestamp()),
            },
            self._secret,
            algorithm=_ALGORITHM,
        )

    def decode(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                issuer=_ISSUER,
                options={"require": ["sub", "exp", "iat", "iss"]},
            )
            return AccessTokenClaims(
                user_id=UUID(payload["sub"]),
                email=payload.get("email", ""),
                role=Role(payload["role"]),
            )
        except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
            raise UserError.INVALID_TOKEN.exception() from exc


__all__ = ["JwtAccessTokenCodec"]
