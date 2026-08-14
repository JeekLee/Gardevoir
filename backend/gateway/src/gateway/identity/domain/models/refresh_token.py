"""리프레시 토큰의 평문과 저장형."""

import hashlib
import secrets
from dataclasses import dataclass, field

_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class RefreshToken:
    value: str = field(repr=False)

    @classmethod
    def generate(cls) -> RefreshToken:
        return cls(secrets.token_urlsafe(_TOKEN_BYTES))

    @property
    def hash(self) -> str:
        """고엔트로피 랜덤이라 빠른 해시로 충분하다.

        ``ApiKey.key`` 와 달리 해시로 저장한다 — 발급 뒤에 이 값을 다시 읽을 일이 없다.
        """
        return hashlib.sha256(self.value.encode()).hexdigest()


__all__ = ["RefreshToken"]
