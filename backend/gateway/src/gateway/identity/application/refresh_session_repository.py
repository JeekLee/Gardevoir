from typing import Protocol
from uuid import UUID

from gateway.identity.domain.models.refresh_session import RefreshSession


class RefreshSessionRepository(Protocol):
    async def find_by_token_hash(self, token_hash: str) -> RefreshSession | None: ...

    async def add(self, session: RefreshSession) -> None: ...

    async def remove(self, session: RefreshSession) -> None:
        """세션을 없앤다 — 로그아웃과 갱신 회전이 부른다."""
        ...

    async def remove_all_for_user(self, user_id: UUID) -> None:
        """비밀번호 변경·비활성화 때 그 사용자의 세션을 전부 끊는다."""
        ...
