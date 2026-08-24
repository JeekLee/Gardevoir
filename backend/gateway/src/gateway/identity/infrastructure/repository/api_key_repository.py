from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.identity.domain.exceptions.api_key_error import ApiKeyError
from gateway.identity.domain.models.api_key import ApiKey
from gateway.identity.infrastructure.mapper.api_key_mapper import to_domain, to_model
from gateway.identity.infrastructure.model.api_key_model import ApiKeyModel


class SqlAlchemyApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_key(self, key: str) -> ApiKey | None:
        row = (
            await self._session.execute(select(ApiKeyModel).where(ApiKeyModel.key == key))
        ).scalar_one_or_none()
        return to_domain(row) if row is not None else None

    async def get(self, api_key_id: UUID) -> ApiKey | None:
        row = await self._session.get(ApiKeyModel, api_key_id)
        return to_domain(row) if row is not None else None

    async def add(self, api_key: ApiKey) -> None:
        self._session.add(to_model(api_key))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # 같은 사용자·이름의 동시 발급이 유일 제약에 걸리면 500 이 아니라 409 다.
            raise ApiKeyError.DUPLICATE_NAME.exception(details={"name": api_key.name}) from exc

    async def save(self, api_key: ApiKey) -> None:
        await self._session.execute(
            update(ApiKeyModel)
            .where(ApiKeyModel.id == api_key.id)
            .values(
                name=api_key.name,
                expires_at=api_key.expires_at,
                revoked_at=api_key.revoked_at,
            )
        )
        await self._session.flush()
