"""리프레시 토큰이 뒷받침하는 로그인 세션.

회수 상태를 들지 않는다 — 저장소가 만료를 TTL 로 처리하므로 세션은 **있거나 없다.**
``ensure_active`` 의 만료 검사는 TTL 경계와 시계 오차에 대한 방어다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from gateway.identity.domain.exceptions.session_error import SessionError
from gateway.identity.domain.models.refresh_token import RefreshToken


@dataclass(frozen=True, slots=True)
class RefreshSession:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime

    @classmethod
    def issue(cls, *, user_id: UUID, token: RefreshToken, ttl: timedelta) -> RefreshSession:
        return cls(
            id=uuid7(),
            user_id=user_id,
            token_hash=token.hash,
            expires_at=datetime.now(UTC) + ttl,
        )

    def ensure_active(self) -> None:
        if self.expires_at <= datetime.now(UTC):
            SessionError.INVALID.raise_()


__all__ = ["RefreshSession"]
