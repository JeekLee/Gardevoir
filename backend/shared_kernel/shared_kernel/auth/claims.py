from dataclasses import dataclass
from uuid import UUID

from shared_kernel.auth.role import Role


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """검증된 액세스 토큰이 실어 나르는 것 = 인증된 주체(principal).

    와이어 DTO 가 아니다(직렬화되지 않는다). 코덱이 디코딩해 핸들러로 흘려보내는 값 객체다.
    """

    user_id: UUID
    email: str
    role: Role


__all__ = ["AccessTokenClaims"]
