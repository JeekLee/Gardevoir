"""콘솔에 로그인하는 사람."""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid7

from gateway.identity.domain.enums.role import Role
from gateway.identity.domain.exceptions.user_error import UserError

_MIN_PASSWORD_LENGTH = 12
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
_MAXMEM = 256 * 1024 * 1024


def normalise_email(email: str) -> str:
    return email.strip().lower()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, dklen=_KEY_BYTES, maxmem=_MAXMEM
    )


def _hash_password(password: str) -> str:
    if len(password) < _MIN_PASSWORD_LENGTH:
        UserError.WEAK_PASSWORD.raise_(details={"min_length": _MIN_PASSWORD_LENGTH})
    salt = secrets.token_bytes(_SALT_BYTES)
    key = _derive(password, salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    name: str
    #: 비용 파라미터를 담고 있어, 값을 올려도 옛 해시가 그대로 검증된다.
    password_hash: str = field(repr=False)
    role: Role = Role.USER
    deactivated_at: datetime | None = None

    @classmethod
    def register(cls, *, email: str, name: str, password: str, role: Role = Role.USER) -> User:
        return cls(
            id=uuid7(),
            email=normalise_email(email),
            name=name,
            password_hash=_hash_password(password),
            role=role,
        )

    def update(self, *, email: str, name: str) -> User:
        self.ensure_active()
        return replace(self, email=normalise_email(email), name=name)

    def set_password(self, password: str) -> User:
        self.ensure_active()
        return replace(self, password_hash=_hash_password(password))

    def change_role(self, role: Role) -> User:
        self.ensure_active()
        if self.role is role:
            return self
        return replace(self, role=role)

    def deactivate(self) -> User:
        if self.deactivated_at is not None:
            return self
        return replace(self, deactivated_at=datetime.now(UTC))

    def ensure_active(self) -> None:
        if self.deactivated_at is not None:
            UserError.DEACTIVATED.raise_(details={"id": str(self.id)})

    def ensure_admin(self) -> None:
        self.ensure_active()
        if self.role is not Role.ADMIN:
            UserError.NOT_ADMIN.raise_(details={"id": str(self.id), "role": str(self.role)})

    def authenticate(self, password: str) -> None:
        self.ensure_active()
        try:
            scheme, n, r, p, salt, expected = self.password_hash.split("$")
            if scheme != "scrypt":
                raise ValueError(scheme)
            candidate = _derive(password, _unb64(salt), n=int(n), r=int(r), p=int(p))
        except ValueError, TypeError:
            # 깨진 해시를 500 으로 흘리면 그 자체가 계정 상태 신호가 된다.
            UserError.INVALID_CREDENTIALS.raise_()
        if not secrets.compare_digest(candidate, _unb64(expected)):
            UserError.INVALID_CREDENTIALS.raise_()


__all__ = ["User", "normalise_email"]
