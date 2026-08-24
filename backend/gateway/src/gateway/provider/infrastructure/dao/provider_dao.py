from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.provider.application.result.provider_result import ProviderSummary
from gateway.provider.infrastructure.model.provider_model import ProviderModel


def _summary(row: ProviderModel) -> ProviderSummary:
    return ProviderSummary(
        id=row.id,
        name=row.name,
        base_url=row.base_url,
        models=list(row.models or []),
        has_api_key=bool(row.api_key),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyProviderDao:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self, provider_id: UUID) -> ProviderSummary | None:
        row = await self._session.get(ProviderModel, provider_id)
        return _summary(row) if row is not None else None

    async def list_summaries(self) -> tuple[list[ProviderSummary], int]:
        rows = (
            (await self._session.execute(select(ProviderModel).order_by(ProviderModel.created_at)))
            .scalars()
            .all()
        )
        return [_summary(r) for r in rows], len(rows)

    async def exists_with_name(self, name: str) -> bool:
        return bool(
            await self._session.scalar(
                select(select(ProviderModel.id).where(ProviderModel.name == name).exists())
            )
        )
