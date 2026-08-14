from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.identity.domain.models.refresh_session import RefreshSession
from gateway.identity.infrastructure.refresh_session_mapper import to_domain, to_model
from gateway.identity.infrastructure.refresh_session_model import RefreshSessionModel


class SqlAlchemyRefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        row = (
            await self._session.execute(
                select(RefreshSessionModel).where(RefreshSessionModel.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        return to_domain(row) if row is not None else None

    async def add(self, session: RefreshSession) -> None:
        self._session.add(to_model(session))
        await self._session.flush()

    async def save(self, session: RefreshSession) -> None:
        await self._session.execute(
            update(RefreshSessionModel)
            .where(RefreshSessionModel.id == session.id)
            .values(revoked_at=session.revoked_at)
        )
        await self._session.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        await self._session.execute(
            update(RefreshSessionModel)
            .where(
                RefreshSessionModel.user_id == user_id,
                RefreshSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.flush()
