import asyncio
import importlib
import pkgutil
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from gateway.settings import get_settings
from shared_kernel.database import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DSN 은 설정에서 온다 — alembic.ini 에 박아두지 않는다.
config.set_main_option("sqlalchemy.url", get_settings().database.dsn)


def _register_orm_models() -> None:
    """``infrastructure`` 아래를 훑어 ``Base.metadata`` 를 완성한다.

    손으로 적은 목록에 의존하면 새 모델을 빠뜨릴 수 있고, 빠진 모델은 autogenerate 가
    **그 테이블을 drop 하는** 마이그레이션을 만든다. 목록을 없애면 그 실패가 성립하지 않는다.

    ``infrastructure`` 로 한정하는 이유: 마이그레이션이 HTTP 계층 임포트에 의존하면 안 된다.
    라우터 하나가 깨져도 DB 는 올릴 수 있어야 한다. 모델은 규약상 각 컨텍스트의
    ``infrastructure/`` 에 있다 (skills/gardevoir-be).
    """
    import gateway

    for module in pkgutil.walk_packages(gateway.__path__, f"{gateway.__name__}."):
        if ".infrastructure" in module.name:
            importlib.import_module(module.name)


_register_orm_models()
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
