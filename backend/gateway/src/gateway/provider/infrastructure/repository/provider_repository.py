from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.provider.domain.exceptions.provider_error import ProviderError
from gateway.provider.domain.models.provider import Provider
from gateway.provider.infrastructure.mapper.provider_mapper import to_domain, to_model
from gateway.provider.infrastructure.model.provider_model import ProviderModel


class SqlAlchemyProviderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, provider_id: UUID) -> Provider | None:
        row = await self._session.get(ProviderModel, provider_id)
        return to_domain(row) if row is not None else None

    async def find_by_model(self, model: str) -> Provider | None:
        # JSONB containment: models @> ["<model>"]. GIN 인덱스가 받친다.
        row = (
            await self._session.execute(
                select(ProviderModel).where(ProviderModel.models.contains([model]))
            )
        ).scalar_one_or_none()
        return to_domain(row) if row is not None else None

    async def add(self, provider: Provider) -> None:
        self._session.add(to_model(provider))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ProviderError.DUPLICATE_NAME.exception(details={"name": provider.name}) from exc

    async def save(self, provider: Provider) -> None:
        await self._session.execute(
            update(ProviderModel)
            .where(ProviderModel.id == provider.id)
            .values(
                name=provider.name,
                base_url=provider.base_url,
                api_key=provider.api_key,
                models=list(provider.models),
            )
        )
        await self._session.flush()

    async def delete(self, provider_id: UUID) -> None:
        await self._session.execute(delete(ProviderModel).where(ProviderModel.id == provider_id))
        await self._session.flush()
