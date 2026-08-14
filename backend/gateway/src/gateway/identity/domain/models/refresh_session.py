"""리프레시 토큰이 뒷받침하는 로그인 세션."""

from dataclasses import dataclass, replace
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
    revoked_at: datetime | None = None

    @classmethod
    def issue(cls, *, user_id: UUID, token: RefreshToken, ttl: timedelta) -> RefreshSession:
        return cls(
            id=uuid7(),
            user_id=user_id,
            token_hash=token.hash,
            expires_at=datetime.now(UTC) + ttl,
        )

    def revoke(self) -> RefreshSession:
        if self.revoked_at is not None:
            return self
        return replace(self, revoked_at=datetime.now(UTC))

    def ensure_active(self) -> None:
        if self.revoked_at is not None or self.expires_at <= datetime.now(UTC):
            SessionError.INVALID.raise_()


__all__ = ["RefreshSession"]
