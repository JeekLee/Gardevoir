"""요청 model 로 업스트림을 정하는 포트. 어댑터는 Provider BC 를 조회한다."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Upstream:
    base_url: str
    #: 로컬 호스팅 프로바이더면 빈 문자열.
    api_key: str


class UpstreamResolver(Protocol):
    async def resolve(self, model: str) -> Upstream:
        """model 을 서빙하는 업스트림. 없으면 PROVIDER-005 로 막는다."""
        ...


__all__ = ["Upstream", "UpstreamResolver"]
