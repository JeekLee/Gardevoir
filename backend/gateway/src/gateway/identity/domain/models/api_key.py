"""프록시를 호출할 수 있는 크레덴셜."""

import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid7

from gateway.identity.domain.exceptions.api_key_error import ApiKeyError

_KEY_PREFIX = "gdv_live_"
_TOKEN_BYTES = 32


def _reject_past(expires_at: datetime | None) -> None:
    if expires_at is not None and expires_at <= datetime.now(UTC):
        ApiKeyError.EXPIRY_IN_PAST.raise_(details={"expires_at": expires_at.isoformat()})


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: UUID
    name: str
    #: 해시가 아니라 원본이다. 되돌리려면 발급된 키를 전부 무효화해야 한다 (SKILL.md).
    key: str = field(repr=False)
    user_id: UUID
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def issue(cls, *, name: str, user_id: UUID, expires_at: datetime | None = None) -> ApiKey:
        _reject_past(expires_at)
        return cls(
            id=uuid7(),
            name=name,
            key=_KEY_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES),
            user_id=user_id,
            expires_at=expires_at,
        )

    def update(self, *, name: str, expires_at: datetime | None) -> ApiKey:
        self.ensure_active()
        _reject_past(expires_at)
        return replace(self, name=name, expires_at=expires_at)

    def revoke(self) -> ApiKey:
        if self.revoked_at is not None:
            return self
        return replace(self, revoked_at=datetime.now(UTC))

    def ensure_active(self) -> None:
        if self.revoked_at is not None:
            ApiKeyError.REVOKED.raise_(details={"id": str(self.id)})
        if self.expires_at is not None and self.expires_at <= datetime.now(UTC):
            ApiKeyError.EXPIRED.raise_(details={"id": str(self.id)})


__all__ = ["ApiKey"]
