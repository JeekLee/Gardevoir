"""Provider 의 요청 수명 배선. 조립 루트는 app.py 다."""

from collections.abc import AsyncIterator

from fastapi import Request

from gateway.provider.application.service.provider_service import ProviderService
from gateway.provider.infrastructure.dao.provider_dao import SqlAlchemyProviderDao
from gateway.provider.infrastructure.repository.provider_repository import (
    SqlAlchemyProviderRepository,
)
from shared_kernel.database import SqlAlchemyUnitOfWork


async def provide_provider_service(request: Request) -> AsyncIterator[ProviderService]:
    async with request.app.state.session_factory() as session:
        yield ProviderService(
            provider_repository=SqlAlchemyProviderRepository(session),
            provider_dao=SqlAlchemyProviderDao(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        )
