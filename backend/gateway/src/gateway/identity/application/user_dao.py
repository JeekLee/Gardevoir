from typing import Protocol
from uuid import UUID

from gateway.identity.application.user_result import UserSummary


class UserDao(Protocol):
    async def get_summary(self, user_id: UUID) -> UserSummary | None: ...

    async def list_summaries(self) -> tuple[list[UserSummary], int]: ...
