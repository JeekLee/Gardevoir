"""ApiKey write interface.

Repository operates on the domain aggregate. 읽기는 Dao 가 result DTO 로 돌려준다
(CQRS-lite).
"""

from typing import Protocol

from gateway.identity.domain.models.api_key import ApiKey


class ApiKeyRepository(Protocol):
    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        """인증 경로. **비활성 키는 돌려주지 않는다.**"""
        ...

    async def get(self, key_id: str) -> ApiKey | None:
        """관리 경로. 비활성 키도 돌려준다 — 다시 켜려면 읽어야 한다."""
        ...

    async def add(self, key: ApiKey) -> None: ...

    async def set_disabled(self, key_id: str, disabled: bool) -> None: ...

    async def has_scope(self, scope: str) -> bool:
        """그 스코프를 가진 활성 키가 하나라도 있는지 — 부트스트랩 판단에 쓴다."""
        ...
