from typing import Protocol
from uuid import UUID

from gateway.identity.domain.models.api_key import ApiKey


class ApiKeyRepository(Protocol):
    async def find_by_key(self, key: str) -> ApiKey | None:
        """프록시 인증 경로 — 요청마다 이 조회 하나로 끝난다 (캐시 없음)."""
        ...

    async def get(self, api_key_id: UUID) -> ApiKey | None: ...

    async def add(self, api_key: ApiKey) -> None: ...

    async def save(self, api_key: ApiKey) -> None: ...
