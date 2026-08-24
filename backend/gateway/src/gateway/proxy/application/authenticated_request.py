"""프록시 요청의 인증 맥락.

키(크레덴셜)는 identity 가 검증하고, 가드레일은 헤더에서 온다. 업스트림은 여기 없다 —
요청 body 의 model 로 Provider 를 조회해 정한다.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthenticatedRequest:
    api_key_id: UUID
    app_name: str
    guardrail: str


__all__ = ["AuthenticatedRequest"]
