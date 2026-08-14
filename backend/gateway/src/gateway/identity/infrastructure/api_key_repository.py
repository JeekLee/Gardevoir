"""SQLAlchemy ApiKey repository."""

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.identity.domain.models.api_key import ApiKey
from gateway.identity.infrastructure.api_key_mapper import to_domain, to_model
from gateway.identity.infrastructure.api_key_model import ApiKeyModel


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

    async def get(self, key_id: str) -> ApiKey | None:
        """관리 경로. 비활성 키도 돌려준다 — 다시 켜려면 읽을 수 있어야 한다."""
        row = await self._session.get(ApiKeyModel, key_id)
        return to_domain(row) if row is not None else None

    async def add(self, key: ApiKey) -> None:
        self._session.add(to_model(key))
        await self._session.flush()

    async def set_disabled(self, key_id: str, disabled: bool) -> None:
        await self._session.execute(
            update(ApiKeyModel).where(ApiKeyModel.id == key_id).values(disabled=disabled)
        )
        await self._session.flush()

    async def has_scope(self, scope: str) -> bool:
        """그 스코프를 가진 **활성** 키가 있는지.

        jsonb 배열 포함 검사다. 비활성 키는 세지 않는다 — 전부 꺼져 있으면 그 스코프로
        할 수 있는 것이 없으므로, 부트스트랩이 다시 필요한 상태다.
        """
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        ApiKeyModel.disabled.is_(False),
                        ApiKeyModel.scopes.contains([scope]),
                    )
                )
            )
        )
