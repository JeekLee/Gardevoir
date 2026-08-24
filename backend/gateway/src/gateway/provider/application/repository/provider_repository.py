from typing import Protocol
from uuid import UUID

from gateway.provider.domain.models.provider import Provider


class ProviderRepository(Protocol):
    async def get(self, provider_id: UUID) -> Provider | None: ...

    async def find_by_model(self, model: str) -> Provider | None:
        """프록시 라우팅 — 요청 model 을 서빙하는 프로바이더. 공급자 비밀을 담아 돌려준다."""
        ...

    async def add(self, provider: Provider) -> None: ...

    async def save(self, provider: Provider) -> None: ...

    async def delete(self, provider_id: UUID) -> None: ...
