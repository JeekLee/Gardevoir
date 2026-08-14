"""리프레시 토큰이 뒷받침하는 로그인 세션.

회수 상태를 들지 않는다 — 저장소가 TTL 로 만료를 처리하므로 세션은 **있거나 없다.**
``ensure_active`` 의 만료 검사는 TTL 경계와 시계 오차에 대한 방어다.
"""

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from gateway.identity.domain.exceptions.session_error import SessionError

_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class RefreshSession:
    id: UUID
    user_id: UUID
    #: 해시가 아니라 토큰 자체다. 저장소가 메모리 전용이라(영속화 끔) 해싱이 막을
    #: '유출된 덤프' 가 존재하지 않는다.
    token: str = field(repr=False)
    expires_at: datetime

    @classmethod
    def issue(cls, *, user_id: UUID, ttl: timedelta) -> RefreshSession:
        return cls(
            id=uuid7(),
            user_id=user_id,
            token=secrets.token_urlsafe(_TOKEN_BYTES),
            expires_at=datetime.now(UTC) + ttl,
        )

    def ensure_active(self) -> None:
        if self.expires_at <= datetime.now(UTC):
            SessionError.INVALID.raise_()


__all__ = ["RefreshSession"]
