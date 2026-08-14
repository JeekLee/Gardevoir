import os
import pathlib

import clickhouse_connect
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import gateway.infrastructure.models  # noqa: F401  Base.metadata 에 모델을 등록한다
from gateway.audit.infrastructure.schema import apply_clickhouse_schema
from gateway.settings import get_settings
from shared_kernel.database import Base

CLICKHOUSE_SQL_DIR = pathlib.Path(__file__).resolve().parents[1] / "clickhouse"

#: 로컬 기본값. 개발자 셸에 이미 있으면 그것을 존중한다.
#: get_settings() 는 lru_cache 지연 호출이라 임포트 시점에는 필요하지 않으므로,
#: 임포트를 위에 두고 여기서 채운다.
_DEFAULTS = {
    "GARDEVOIR_APP_NAME": "gateway",
    "GARDEVOIR_DATABASE__DSN": (
        "postgresql+psycopg://gardevoir:gardevoir@localhost:21010/gardevoir"
    ),
    "GARDEVOIR_CLICKHOUSE__HOST": "localhost",
    "GARDEVOIR_CLICKHOUSE__PORT": "21020",
    "GARDEVOIR_CLICKHOUSE__USER": "gardevoir",
    "GARDEVOIR_CLICKHOUSE__PASSWORD": "gardevoir",
    "GARDEVOIR_CLICKHOUSE__DATABASE": "gardevoir",
}

for _key, _value in _DEFAULTS.items():
    os.environ.setdefault(_key, _value)


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Session-scoped engine with a freshly created schema.

    Postgres 가 먼저 떠 있어야 한다 — infra/README.md 참조.
    """
    eng = create_async_engine(get_settings().database.dsn)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    """Per-test session; every table is truncated afterwards."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.exec_driver_sql(f'TRUNCATE TABLE "{table.name}" CASCADE')


@pytest.fixture(scope="session")
def ch_client():
    """ClickHouse client. 컨테이너가 떠 있어야 한다 — infra/README.md 참조."""
    ch = get_settings().clickhouse
    return clickhouse_connect.get_client(
        host=ch.host,
        port=ch.port,
        username=ch.user,
        password=ch.password,
        database=ch.database,
    )


@pytest.fixture
def audit_table(ch_client):
    """Fresh audit_events table per test."""
    ch_client.command("DROP TABLE IF EXISTS audit_events")
    apply_clickhouse_schema(ch_client, CLICKHOUSE_SQL_DIR)
    yield
