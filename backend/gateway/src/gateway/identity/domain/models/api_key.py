"""ApiKey aggregate.

**프록시를 호출할 수 있는 크레덴셜, 그것뿐이다.** 어떤 가드레일을 쓸 수 있는지, admin
표면에 접근할 수 있는지는 이 집합체의 관심사가 아니다 — 크레덴셜의 정체성이 아니라 그
크레덴셜에 붙은 권한이고, 회원 설계에서 자리를 정한다 (§14).

Persistence-ignorant: no SQLAlchemy, no FastAPI, no httpx.

**원본 키를 그대로 저장한다.** 해시만 저장하면 DB 덤프가 유출돼도 인증에 쓸 수 없지만,
자체 호스팅에서 DB 접근자가 곧 운영자라는 판단으로 원본 저장을 택했다. 되돌리기가 어렵다 —
해시로 바꾸는 순간 발급된 키가 전부 무효가 된다.

시각은 tz-aware 만 받는다. naive 는 순간을 지시하지 않으므로 명령 DTO 가 ``AwareDatetime``
으로 막는다 — 여기까지 오면 비교에서 TypeError(500)가 났다.
"""

import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid7

from gateway.identity.domain.exceptions.api_key_error import ApiKeyError

_KEY_PREFIX = "gdv_live_"
_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: UUID
    name: str
    #: 원본 키. repr 에서 빼는 것은 집합체를 로그에 찍는 실수 하나로 크레덴셜이 새는
    #: 것을 막기 위한 것뿐이다.
    key: str = field(repr=False)
    #: 발급한 사람. 회원 설계 후 FK 로 승격한다.
    user_id: UUID
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def issue(cls, *, name: str, user_id: UUID, expires_at: datetime | None = None) -> ApiKey:
        if expires_at is not None and expires_at <= datetime.now(UTC):
            ApiKeyError.EXPIRY_IN_PAST.raise_(details={"expires_at": expires_at.isoformat()})
        return cls(
            id=uuid7(),
            name=name,
            key=_KEY_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES),
            user_id=user_id,
            expires_at=expires_at,
        )

    def update(self, *, name: str, expires_at: datetime | None) -> ApiKey:
        """이름·만료를 바꾼 사본.

        두 필드를 다 요구한다. ``expires_at=None`` 에 기본값을 주면 "안 바꿈"과 "만료
        없앰"이 구분되지 않는다. 일부만 보내는 요청은 서비스가 불러온 집합체에서 채운다.

        만료를 과거로 잡지 못하게 하는 이유: 허용하면 키를 죽이는 방법이 둘이 되고 그중
        하나는 ``revoked_at`` 을 남기지 않는다 — "왜 죽었나"의 답이 갈린다. 즉시 무력화는
        ``revoke()`` 가 한다.
        """
        if self.revoked_at is not None:
            ApiKeyError.REVOKED.raise_(details={"id": str(self.id)})
        if expires_at is not None and expires_at <= datetime.now(UTC):
            ApiKeyError.EXPIRY_IN_PAST.raise_(details={"expires_at": expires_at.isoformat()})
        return replace(self, name=name, expires_at=expires_at)

    def revoke(self) -> ApiKey:
        """회수된 사본. 이미 회수됐으면 그대로 돌려준다 — 회수는 멱등이다.

        행을 지우지 않는 이유: 감사 로그가 ``api_key_id`` 를 참조하므로, 지우면 과거
        기록이 어느 키의 것인지 알 수 없어진다 (§10).
        """
        if self.revoked_at is not None:
            return self
        return replace(self, revoked_at=datetime.now(UTC))

    def require_usable(self) -> None:
        """회수·만료 판정.

        현재 시각을 인자로 받지 않는다. 만료 검사에 시각을 넘겨받으면 그것이 우회 경로가
        된다 — 잘못된 값을 넘기면 만료된 키가 통과한다.
        """
        if self.revoked_at is not None:
            ApiKeyError.REVOKED.raise_(details={"id": str(self.id)})
        if self.expires_at is not None and self.expires_at <= datetime.now(UTC):
            ApiKeyError.EXPIRED.raise_(details={"id": str(self.id)})


__all__ = ["ApiKey"]
