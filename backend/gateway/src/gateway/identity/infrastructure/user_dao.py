from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.identity.application.user_result import UserSummary
from gateway.identity.domain.enums.role import Role
from gateway.identity.infrastructure.user_model import UserModel


def _summary(row: UserModel) -> UserSummary:
    return UserSummary(
        id=row.id,
        email=row.email,
        name=row.name,
        role=Role(row.role),
        deactivated_at=row.deactivated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyUserDao:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self, user_id: UUID) -> UserSummary | None:
        row = await self._session.get(UserModel, user_id)
        return _summary(row) if row is not None else None

    async def list_summaries(self) -> tuple[list[UserSummary], int]:
        rows = (
            (await self._session.execute(select(UserModel).order_by(UserModel.created_at)))
            .scalars()
            .all()
        )
        return [_summary(row) for row in rows], len(rows)
