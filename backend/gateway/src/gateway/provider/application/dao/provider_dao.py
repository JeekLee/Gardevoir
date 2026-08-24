from typing import Protocol
from uuid import UUID

from gateway.provider.application.result.provider_result import ProviderSummary


class ProviderDao(Protocol):
    async def get_summary(self, provider_id: UUID) -> ProviderSummary | None: ...

    async def list_summaries(self) -> tuple[list[ProviderSummary], int]: ...

    async def exists_with_name(self, name: str) -> bool: ...
