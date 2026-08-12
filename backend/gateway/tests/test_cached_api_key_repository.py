from gateway.domain.models.api_key import ApiKey, generate_key, hash_key
from gateway.infrastructure.repository.cached_api_key_repository import (
    CachedApiKeyRepository,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class CountingRepository:
    """Records how often the slow path was taken."""

    def __init__(self, keys: dict[str, ApiKey] | None = None) -> None:
        self.keys = keys or {}
        self.lookups = 0
        self.added: list[ApiKey] = []

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        self.lookups += 1
        return self.keys.get(key_hash)

    async def add(self, key: ApiKey) -> None:
        self.added.append(key)
        self.keys[key.key_hash] = key


def _key(raw: str) -> ApiKey:
    return ApiKey(
        id="k1",
        name="app",
        key_hash=hash_key(raw),
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=("base",),
        default_guardrail="base",
    )


async def test_second_lookup_does_not_touch_the_inner_repository():
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    first = await cache.find_by_hash(hash_key(raw))
    second = await cache.find_by_hash(hash_key(raw))
    assert first is not None and first.id == "k1"
    assert second is not None and second.id == "k1"
    assert inner.lookups == 1
    assert cache.hits == 1
    assert cache.misses == 1


async def test_entry_expires_after_ttl():
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    clock = FakeClock()
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=clock)

    await cache.find_by_hash(hash_key(raw))
    clock.advance(31.0)
    await cache.find_by_hash(hash_key(raw))
    assert inner.lookups == 2


async def test_entry_is_still_valid_just_before_expiry():
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    clock = FakeClock()
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=clock)

    await cache.find_by_hash(hash_key(raw))
    clock.advance(29.0)
    await cache.find_by_hash(hash_key(raw))
    assert inner.lookups == 1


async def test_unknown_key_is_negative_cached():
    """무효한 키를 반복 전송하는 것만으로 DB에 부하를 줄 수 있어서는 안 된다."""
    inner = CountingRepository()
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())
    digest = hash_key(generate_key())

    assert await cache.find_by_hash(digest) is None
    assert await cache.find_by_hash(digest) is None
    assert inner.lookups == 1
    assert cache.hits == 1


async def test_invalidate_forces_reload():
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    await cache.find_by_hash(hash_key(raw))
    cache.invalidate(hash_key(raw))
    await cache.find_by_hash(hash_key(raw))
    assert inner.lookups == 2


async def test_clear_drops_every_entry():
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    await cache.find_by_hash(hash_key(raw))
    cache.clear()
    await cache.find_by_hash(hash_key(raw))
    assert inner.lookups == 2


async def test_add_invalidates_so_the_new_key_is_visible():
    """등록 직후 조회가 부정 캐시에 막히면 새 키가 TTL 동안 죽는다."""
    raw = generate_key()
    inner = CountingRepository()
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    assert await cache.find_by_hash(hash_key(raw)) is None  # 부정 캐시 적재
    await cache.add(_key(raw))

    found = await cache.find_by_hash(hash_key(raw))
    assert found is not None
    assert found.id == "k1"


async def test_add_reaches_the_inner_repository():
    raw = generate_key()
    inner = CountingRepository()
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    await cache.add(_key(raw))
    assert [k.key_hash for k in inner.added] == [hash_key(raw)]


async def test_cache_is_keyed_by_hash_not_raw_key():
    """캐시 구조에 원본 크레덴셜이 남으면 메모리 덤프로 유출된다."""
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())
    await cache.find_by_hash(hash_key(raw))

    assert all(raw not in k for k in cache._entries)
    assert hash_key(raw) in cache._entries


async def test_distinct_keys_do_not_share_entries():
    raw_a, raw_b = generate_key(), generate_key()
    inner = CountingRepository({hash_key(raw_a): _key(raw_a)})
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    assert await cache.find_by_hash(hash_key(raw_a)) is not None
    assert await cache.find_by_hash(hash_key(raw_b)) is None
    assert inner.lookups == 2
