"""In-memory caching decorator over an ApiKeyRepository.

§6 은 요청 경로에 DB 접근이 없을 것을 요구한다. 키 조회가 유일한 DB 접근이므로
여기서 덮는다. 존재하지 않는 키도 캐싱한다 — 그러지 않으면 무효한 키를 반복
전송하는 것만으로 DB에 부하를 줄 수 있다.

레이어링은 의존 방향을 규정하고 캐싱은 구현 자유다. 이 클래스가 리포지토리
Protocol 을 그대로 구현하므로 서비스는 캐시의 존재를 모른다.
"""

import time
from collections.abc import Callable

from gateway.application.repository.api_key_repository import ApiKeyRepository
from gateway.domain.models.api_key import ApiKey


class CachedApiKeyRepository:
    def __init__(
        self,
        inner: ApiKeyRepository,
        *,
        ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl_s = ttl_s
        self._clock = clock
        #: key_hash -> (expires_at, value). The raw key never appears here.
        self._entries: dict[str, tuple[float, ApiKey | None]] = {}
        self.hits = 0
        self.misses = 0

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        now = self._clock()
        entry = self._entries.get(key_hash)
        if entry is not None and entry[0] > now:
            self.hits += 1
            return entry[1]

        self.misses += 1
        value = await self._inner.find_by_hash(key_hash)
        self._entries[key_hash] = (now + self._ttl_s, value)
        return value

    async def add(self, key: ApiKey) -> None:
        await self._inner.add(key)
        # 부정 캐시가 남아 있으면 새 키가 TTL 동안 죽는다.
        self.invalidate(key.key_hash)

    def invalidate(self, key_hash: str) -> None:
        self._entries.pop(key_hash, None)

    def clear(self) -> None:
        self._entries.clear()
