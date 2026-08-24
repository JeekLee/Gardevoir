from typing import Protocol

from shared_kernel.auth.claims import AccessTokenClaims


class AccessTokenVerifier(Protocol):
    """검증측 계약. 서버가 쪼개지면 하류 서비스가 이것만 필요로 한다 — 공개키로 검증만 하고
    서명(발급)은 못 한다 (RS256 의 검증측). 발급 계약은 auth 서비스에 따로 산다.
    """

    def decode(self, token: str) -> AccessTokenClaims: ...


__all__ = ["AccessTokenVerifier"]
