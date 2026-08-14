from typing import Protocol
from uuid import UUID

from gateway.identity.domain.models.user import User


class UserRepository(Protocol):
    async def find_by_email(self, email: str) -> User | None: ...

    async def get(self, user_id: UUID) -> User | None: ...

    async def add(self, user: User) -> None: ...

    async def save(self, user: User) -> None: ...

    async def count_active_admins(self) -> int:
        """마지막 관리자를 강등·비활성화하지 못하게 하는 데 쓴다."""
        ...

    async def is_empty(self) -> bool:
        """루트 계정 부트스트랩 판단."""
        ...
