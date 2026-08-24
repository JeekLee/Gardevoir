"""Access token codec — HS256 JWT.

jwt 는 순수 인프로세스 변환이다(키로 문자열을 서명/검증, I/O 없음). 그래서 포트/어댑터로
감싸지 않고 여기서 직접 다룬다 — PasswordHash 가 hashlib.scrypt 를 직접 다루는 것과 같다.
포트는 외부 I/O(httpx·sqlalchemy·clickhouse)를 위한 것이다.

단일 프로세스가 서명하고 검증하므로 대칭 키다(HS256). 서버가 쪼개지면 비대칭(RS256)으로
바꿔 검증측에 공개키만 주면 된다 — 그때 encode/decode 를 나눈다. 지금 미리 나누지 않는다.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from shared_kernel.auth.claims import AccessTokenClaims
from shared_kernel.auth.errors import AuthError
from shared_kernel.auth.role import Role

_ALGORITHM = "HS256"
_ISSUER = "gardevoir"


class AccessTokenCodec:
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
            raise AuthError.INVALID_TOKEN.exception() from exc


__all__ = ["AccessTokenCodec"]
