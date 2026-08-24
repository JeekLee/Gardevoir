"""업스트림 LLM 프로바이더 — 요청이 포워드되는 곳.

프론티어 API(OpenAI 등)든 로컬 호스팅(vLLM 등)이든 같은 추상이다: OpenAI 호환 엔드포인트
(base_url) + 선택적 api_key. 프론티어는 키가 있고, 로컬은 비어 있을 수 있다.

요청 body 의 ``model`` 이 이 프로바이더의 ``models`` 에 있으면 여기로 포워드된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from uuid import UUID, uuid7

from gateway.provider.domain.exceptions.provider_error import ProviderError


@dataclass(frozen=True, slots=True)
class Provider:
    id: UUID
    name: str
    base_url: str
    #: 공급자 비밀. 로컬 호스팅이면 비어 있을 수 있다. DAO 는 이 값을 프로젝션하지 않는다.
    api_key: str = field(repr=False)
    #: 이 프로바이더가 서빙하는 모델명. 요청 ``model`` 이 여기 매칭되면 라우팅된다.
    models: tuple[str, ...] = ()

    @classmethod
    def register(
        cls, *, name: str, base_url: str, api_key: str, models: tuple[str, ...]
    ) -> Provider:
        _reject_empty_models(models)
        return cls(id=uuid7(), name=name, base_url=base_url, api_key=api_key, models=models)

    def update(
        self, *, name: str, base_url: str, api_key: str, models: tuple[str, ...]
    ) -> Provider:
        _reject_empty_models(models)
        return replace(self, name=name, base_url=base_url, api_key=api_key, models=models)


def _reject_empty_models(models: tuple[str, ...]) -> None:
    if not models:
        ProviderError.NO_MODELS.raise_()


__all__ = ["Provider"]
