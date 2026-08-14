"""Redis client lifecycle. ``database/engine.py`` · ``clickhouse/client.py`` 와 같은 모양이다."""

from redis.asyncio import Redis

from shared_kernel.config import RedisSettings

_clients: list[Redis] = []


def get_redis_client(settings: RedisSettings) -> Redis:
    client = Redis(
        host=settings.host,
        port=settings.port,
        db=settings.db,
        password=settings.password or None,
        decode_responses=True,
    )
    _clients.append(client)
    return client


async def dispose_redis() -> None:
    while _clients:
        await _clients.pop().aclose()


__all__ = ["dispose_redis", "get_redis_client"]
