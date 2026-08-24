"""Access token issuing — the sign side.

검증(decode)은 shared_kernel.auth 로 갔다. 발급(서명)은 auth 서비스만 하므로 여기 남는다 —
서버가 쪼개지면 개인키를 쥔 identity 만 이 포트를 구현한다 (RS256 의 서명측).
"""

from typing import Protocol
from uuid import UUID

from shared_kernel.auth import Role


class AccessTokenIssuer(Protocol):
    @property
    def ttl_seconds(self) -> int: ...

    def encode(self, *, user_id: UUID, email: str, role: Role) -> str: ...


__all__ = ["AccessTokenIssuer"]
