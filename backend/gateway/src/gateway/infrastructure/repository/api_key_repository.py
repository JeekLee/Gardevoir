"""SQLAlchemy ApiKey repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.domain.models.api_key import ApiKey
from gateway.infrastructure.mappers.api_key import to_domain, to_model
from gateway.infrastructure.models.api_key import ApiKeyModel


class SqlAlchemyApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        row = (
            await self._session.execute(
                select(ApiKeyModel).where(
                    ApiKeyModel.key_hash == key_hash,
                    # 비활성 키가 조회되면 키 회수가 무의미해진다.
                    ApiKeyModel.disabled.is_(False),
                )
            )
        ).scalar_one_or_none()
        return to_domain(row) if row is not None else None

    async def add(self, key: ApiKey) -> None:
        self._session.add(to_model(key))
        await self._session.flush()
