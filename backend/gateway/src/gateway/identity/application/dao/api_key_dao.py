from typing import Protocol
from uuid import UUID

from gateway.identity.application.result.api_key_result import ApiKeySummary


class ApiKeyDao(Protocol):
    async def get_summary(self, api_key_id: UUID) -> ApiKeySummary | None: ...

    async def list_for_user(self, user_id: UUID) -> tuple[list[ApiKeySummary], int]: ...

    async def exists_for_user_with_name(self, user_id: UUID, name: str) -> bool: ...
