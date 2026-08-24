"""Provider BC 를 조회해 업스트림을 정한다. 프록시 경로 — 요청마다 조회 하나."""

from gateway.provider.domain.exceptions.provider_error import ProviderError
from gateway.provider.infrastructure.repository.provider_repository import (
    SqlAlchemyProviderRepository,
)
from gateway.proxy.application.port.upstream_resolver import Upstream


class ProviderUpstreamResolver:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def resolve(self, model: str) -> Upstream:
        async with self._session_factory() as session:
            provider = await SqlAlchemyProviderRepository(session).find_by_model(model)
        if provider is None:
            ProviderError.NO_PROVIDER_FOR_MODEL.raise_(details={"model": model})
        return Upstream(base_url=provider.base_url, api_key=provider.api_key)


__all__ = ["ProviderUpstreamResolver"]
