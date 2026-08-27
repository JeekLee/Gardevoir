"""Lazy ClickHouse engine and session factory."""

from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from shared_kernel.config import ClickHouseSettings

_engines: list[Engine] = []


@lru_cache
def _get_clickhouse_engine(
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
) -> Engine:
    url = URL.create(
        "clickhousedb+connect",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    )
    engine = create_engine(url, pool_pre_ping=True, server_side_params=True)
    _engines.append(engine)
    return engine


def get_clickhouse_engine(settings: ClickHouseSettings) -> Engine:
    return _get_clickhouse_engine(
        settings.host,
        settings.port,
        settings.user,
        settings.password,
        settings.database,
    )


@lru_cache
def get_clickhouse_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def dispose_clickhouse_engine() -> None:
    while _engines:
        _engines.pop().dispose()
    _get_clickhouse_engine.cache_clear()
    get_clickhouse_session_factory.cache_clear()


__all__ = [
    "dispose_clickhouse_engine",
    "get_clickhouse_engine",
    "get_clickhouse_session_factory",
]
