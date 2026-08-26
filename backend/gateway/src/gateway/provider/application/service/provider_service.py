"""Provider 관리 — 관리자 CRUD. 라우팅(find_by_model)은 proxy 가 repository 로 직접 쓴다."""

import logging
from uuid import UUID

from gateway.provider.application.command.provider_command import CreateProvider, UpdateProvider
from gateway.provider.application.dao.provider_dao import ProviderDao
from gateway.provider.application.repository.provider_repository import ProviderRepository
from gateway.provider.application.result.provider_result import ProviderSummary
from gateway.provider.domain.exceptions.provider_error import ProviderError
from gateway.provider.domain.models.provider import Provider
from shared_kernel.api import Page
from shared_kernel.database import UnitOfWork

logger = logging.getLogger(__name__)


class ProviderService:
    def __init__(
        self,
        *,
        provider_repository: ProviderRepository,
        provider_dao: ProviderDao,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._provider_repository = provider_repository
        self._provider_dao = provider_dao
        self._unit_of_work = unit_of_work

    async def create(self, cmd: CreateProvider) -> ProviderSummary:
        provider = Provider.register(
            name=cmd.name,
            base_url=str(cmd.base_url),
            api_key=cmd.api_key,
            models=tuple(cmd.models),
        )
        async with self._unit_of_work:
            if await self._provider_dao.exists_with_name(cmd.name):
                ProviderError.DUPLICATE_NAME.raise_(details={"name": cmd.name})
            await self._reject_taken_models(cmd.models, exclude=None)
            await self._provider_repository.add(provider)
            summary = await self._summary(provider.id)
        logger.info("provider %r registered (models=%s)", provider.name, list(cmd.models))
        return summary

    async def update(self, provider_id: UUID, cmd: UpdateProvider) -> ProviderSummary:
        provider = await self._load(provider_id)
        async with self._unit_of_work:
            await self._reject_taken_models(cmd.models, exclude=provider_id)
            await self._provider_repository.save(
                provider.update(
                    name=cmd.name,
                    base_url=str(cmd.base_url),
                    api_key=provider.api_key if cmd.api_key is None else cmd.api_key,
                    models=tuple(cmd.models),
                )
            )
            return await self._summary(provider_id)

    async def delete(self, provider_id: UUID) -> None:
        await self._load(provider_id)
        async with self._unit_of_work:
            await self._provider_repository.delete(provider_id)

    async def list(self) -> Page[ProviderSummary]:
        items, total = await self._provider_dao.list_summaries()
        return Page(items=items, total=total)

    async def _reject_taken_models(self, models: list[str], *, exclude: UUID | None) -> None:
        """한 모델은 한 프로바이더만 서빙한다 — 라우팅이 모호해지지 않게."""
        for model in models:
            owner = await self._provider_repository.find_by_model(model)
            if owner is not None and owner.id != exclude:
                ProviderError.MODEL_TAKEN.raise_(details={"model": model, "provider": owner.name})

    async def _load(self, provider_id: UUID) -> Provider:
        provider = await self._provider_repository.get(provider_id)
        if provider is None:
            ProviderError.NOT_FOUND.raise_(details={"id": str(provider_id)})
        return provider

    async def _summary(self, provider_id: UUID) -> ProviderSummary:
        summary = await self._provider_dao.get_summary(provider_id)
        assert summary is not None
        return summary


__all__ = ["ProviderService"]
