"""``scrypt$n$r$p$salt$key``."""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field

from gateway.identity.domain.exceptions.user_error import UserError

_MIN_PASSWORD_LENGTH = 12
_SCHEME = "scrypt"
_N = 2**15
_R = 8
_P = 1
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


@dataclass(frozen=True, slots=True)
class PasswordHash:
    value: str = field(repr=False)

    @classmethod
    def of(cls, password: str) -> PasswordHash:
        if len(password) < _MIN_PASSWORD_LENGTH:
            UserError.WEAK_PASSWORD.raise_(details={"min_length": _MIN_PASSWORD_LENGTH})
        salt = secrets.token_bytes(_SALT_BYTES)
        key = _derive(password, salt, n=_N, r=_R, p=_P)
        return cls(f"{_SCHEME}${_N}${_R}${_P}${_b64(salt)}${_b64(key)}")

    def matches(self, password: str) -> bool:
        """저장된 값에서 비용 파라미터를 읽으므로, 값을 올려도 옛 해시가 검증된다."""
        try:
            scheme, n, r, p, salt, expected = self.value.split("$")
            if scheme != _SCHEME:
                raise ValueError(scheme)
            candidate = _derive(password, _unb64(salt), n=int(n), r=int(r), p=int(p))
        except ValueError, TypeError:
            return False
        return secrets.compare_digest(candidate, _unb64(expected))


__all__ = ["PasswordHash"]
