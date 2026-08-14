"""Access token issuing and verification."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from gateway.identity.domain.enums.role import Role


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    email: str
    role: Role


class AccessTokenCodec(Protocol):
    @property
    def ttl_seconds(self) -> int: ...

    def encode(self, *, user_id: UUID, email: str, role: Role) -> str: ...

    def decode(self, token: str) -> AccessTokenClaims: ...


__all__ = ["AccessTokenClaims", "AccessTokenCodec"]
