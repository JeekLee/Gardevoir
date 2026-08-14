"""User aggregate.

**콘솔에 로그인해 API 키를 발급·회수하는 사람.** ``ApiKey`` 가 "이 호출자가 프록시를
호출할 수 있나"만 답하는 것과 짝이다 — 이쪽은 "이 사람이 로그인할 수 있나"만 답한다.

Persistence-ignorant: no SQLAlchemy, no FastAPI, no httpx.

**기준선은 "활성 사용자면 운영자다"** 이고 그것은 ``require_active()`` 가 답한다. 키 발급과
가드레일 저작은 모든 활성 사용자가 한다.

``role`` 은 그 위에 얹히는 관문 하나다 — 운영자 중에서도 사용자를 만들고 비활성화하고 역할을
바꾸는 사람이 있어야 한다. 값이 둘이라 별도 연관이 아니라 필드로 두었다. **자원별 권한**
("이 사람은 감사만 읽는다")은 사용자의 정체성이 아니므로 그때 별도 연관으로 들어온다 — 그
경계를 지금 넘지 않는다 (AGENTS.md 도메인 모델링 원칙 1).

**비밀번호는 해시한다 — ``ApiKey`` 와 반대다.** 그 차이가 중요하다:

    ApiKey.key    고엔트로피 랜덤. DB 를 읽는 사람이 곧 운영자이므로 평문 저장
    User          사람이 고른 저엔트로피 문자열. **다른 사이트에서 재사용된다**

즉 사용자 비밀번호가 평문으로 새면 우리 시스템이 아니라 그 사람의 *다른 계정*이 뚫린다.
우리가 감수할 수 있는 위험이 아니다. 그리고 로그인은 요청 경로가 아니므로(§6 은 프록시
경로에만 적용된다) 느린 KDF 를 쓸 수 있다 — scrypt n=2^15 에서 94 ms · 32 MB.

scrypt 는 표준 라이브러리에 있다. argon2/bcrypt 의존성을 더할 이유가 없다.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid7

from gateway.identity.domain.enums.role import Role
from gateway.identity.domain.exceptions.user_error import UserError

#: NIST SP 800-63B: 길이만 요구하고 구성 규칙(대문자·기호…)은 두지 않는다 — 구성 규칙은
#: 사람을 예측 가능한 패턴으로 몰아 오히려 약해진다.
_MIN_PASSWORD_LENGTH = 12

#: 비용 파라미터를 해시 문자열에 담는다. 나중에 올릴 때 기존 해시를 그대로 검증할 수 있다.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
_MAXMEM = 256 * 1024 * 1024


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, dklen=_KEY_BYTES, maxmem=_MAXMEM
    )


def _hash_password(password: str) -> str:
    """``scrypt$n$r$p$salt$key``."""
    if len(password) < _MIN_PASSWORD_LENGTH:
        UserError.WEAK_PASSWORD.raise_(details={"min_length": _MIN_PASSWORD_LENGTH})
    salt = secrets.token_bytes(_SALT_BYTES)
    key = _derive(password, salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    #: 로그인 식별자. 소문자로 정규화해 둔다 — 대소문자만 다른 두 이메일은 같은 로그인이다.
    email: str
    name: str
    #: ``scrypt$n$r$p$salt$key``. 평문은 어디에도 남지 않는다.
    #:
    #: ``repr`` 에서 뺀다. 해시는 되돌릴 수 없으므로 ``ApiKey.key`` 처럼 즉시 쓸 수 있는
    #: 크레덴셜은 아니지만, 로그로 새면 오프라인 대입에 쓸 재료가 된다. 빼는 비용이 0 이다.
    password_hash: str = field(repr=False)
    role: Role = Role.USER
    deactivated_at: datetime | None = None

    @classmethod
    def register(cls, *, email: str, name: str, password: str, role: Role = Role.USER) -> User:
        """가입. 평문 비밀번호가 이 메서드 밖으로 나가지 않는다.

        호출자가 해시를 만들 수 없으므로 "평문을 저장하지 않는다"를 틀릴 방법이 없다.
        """
        return cls(
            id=uuid7(),
            email=normalise_email(email),
            name=name,
            password_hash=_hash_password(password),
            role=role,
        )

    def update(self, *, email: str, name: str) -> User:
        """이메일·이름을 바꾼 사본.

        두 필드를 다 요구한다 — 일부만 보내는 요청은 서비스가 불러온 집합체에서 채운다.
        """
        self.require_active()
        return replace(self, email=normalise_email(email), name=name)

    def set_password(self, password: str) -> User:
        self.require_active()
        return replace(self, password_hash=_hash_password(password))

    def change_role(self, role: Role) -> User:
        """역할을 바꾼 사본. 같은 역할이면 그대로 돌려준다 — 멱등이다.

        ``update()`` 에 넣지 않았다. 남의 역할을 바꾸는 것은 이름을 고치는 것과 다른 권한의
        작업이다.

        "마지막 ADMIN 을 강등할 수 없다" 는 여기서 못 본다 — 다른 ADMIN 이 몇 명인지 세야
        하므로 서비스의 일이다.
        """
        self.require_active()
        if self.role is role:
            return self
        return replace(self, role=role)

    def require_admin(self) -> None:
        """최고 관리자 관문.

        ``require_role(role)`` 로 일반화하지 않았다. 값이 둘이고 ADMIN 이 USER 를 포함하므로
        기준선(``require_active``)과 관문(이것) 둘로 끝난다. 세 번째 역할이 생기면 그때
        순서를 도입한다.
        """
        self.require_active()
        if self.role is not Role.ADMIN:
            UserError.NOT_ADMIN.raise_(details={"id": str(self.id), "role": str(self.role)})

    def deactivate(self) -> User:
        """비활성화된 사본. 이미 비활성이면 그대로 돌려준다 — 멱등이다.

        행을 지우지 않는다: 발급한 API 키가 ``user_id`` 로 이 사람을 참조하므로, 지우면
        "누가 발급했나"를 알 수 없어진다.
        """
        if self.deactivated_at is not None:
            return self
        return replace(self, deactivated_at=datetime.now(UTC))

    def require_active(self) -> None:
        if self.deactivated_at is not None:
            UserError.DEACTIVATED.raise_(details={"id": str(self.id)})

    def require_password(self, password: str) -> None:
        """비밀번호를 검증한다. 틀리면 ``INVALID_CREDENTIALS``.

        불리언이 아니라 예외를 내는 이유: 호출자가 검사 결과를 무시할 수 없다.

        저장된 해시에서 비용 파라미터를 읽으므로, 파라미터를 올려도 옛 해시가 그대로
        검증된다. 비교는 ``compare_digest`` 로 한다 — 조기 반환하는 비교는 일치하는
        접두어 길이를 시간으로 흘린다.
        """
        try:
            scheme, n, r, p, salt, expected = self.password_hash.split("$")
            if scheme != "scrypt":
                raise ValueError(scheme)
            candidate = _derive(password, _unb64(salt), n=int(n), r=int(r), p=int(p))
        except ValueError, TypeError:
            # 저장된 해시가 깨졌으면 인증 실패로 처리한다 — 로그인 경로에서 500 을 내면
            # 그 자체로 계정의 상태를 알려주는 신호가 된다.
            UserError.INVALID_CREDENTIALS.raise_()
        if not secrets.compare_digest(candidate, _unb64(expected)):
            UserError.INVALID_CREDENTIALS.raise_()


def normalise_email(email: str) -> str:
    """대소문자와 주변 공백을 없앤다.

    도메인 규칙이다 — "대소문자만 다른 두 이메일은 같은 로그인"은 정책이지 형식이 아니다.
    형식이 이메일인지(``@`` 가 있는지 등)는 전송 계층이 ``EmailStr`` 로 본다
    (AGENTS.md 도메인 모델링 원칙 6).
    """
    return email.strip().lower()


__all__ = ["User", "normalise_email"]
