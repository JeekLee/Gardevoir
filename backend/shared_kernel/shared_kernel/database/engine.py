"""Lazy engine and session factory.

Cached so repeated composition calls reuse one pool, and disposed in the app
lifespan. Engines are tracked in a list because ``lru_cache`` does not expose
its values.
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engines: list[AsyncEngine] = []


@lru_cache
def get_engine(dsn: str, *, echo: bool = False) -> AsyncEngine:
    engine = create_async_engine(dsn, echo=echo, pool_pre_ping=True)
    _engines.append(engine)
    return engine


@lru_cache
def get_session_factory(dsn: str, *, echo: bool = False) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(dsn, echo=echo), expire_on_commit=False)


async def dispose_engine() -> None:
    while _engines:
        await _engines.pop().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
