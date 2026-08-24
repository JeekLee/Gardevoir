from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.identity.application.result.api_key_result import ApiKeySummary
from gateway.identity.infrastructure.model.api_key_model import ApiKeyModel


def _preview(key: str) -> str:
    """prefix…last4. 원본을 목록·로그에 흘리지 않되 어느 키인지는 알아보게."""
    return f"{key[:12]}…{key[-4:]}" if len(key) > 16 else key


def _summary(row: ApiKeyModel) -> ApiKeySummary:
    return ApiKeySummary(
        id=row.id,
        name=row.name,
        key_preview=_preview(row.key),
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyApiKeyDao:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self, api_key_id: UUID) -> ApiKeySummary | None:
        row = await self._session.get(ApiKeyModel, api_key_id)
        return _summary(row) if row is not None else None

    async def list_for_user(self, user_id: UUID) -> tuple[list[ApiKeySummary], int]:
        rows = (
            (
                await self._session.execute(
                    select(ApiKeyModel)
                    .where(ApiKeyModel.user_id == user_id)
                    .order_by(ApiKeyModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [_summary(r) for r in rows], len(rows)

    async def exists_for_user_with_name(self, user_id: UUID, name: str) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    select(ApiKeyModel.id)
                    .where(ApiKeyModel.user_id == user_id, ApiKeyModel.name == name)
                    .exists()
                )
            )
        )
