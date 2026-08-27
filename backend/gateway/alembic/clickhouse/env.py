from logging.config import fileConfig
from pathlib import Path

from clickhouse_connect.cc_sqlalchemy import alembic as clickhouse_alembic
from sqlalchemy.engine import Connection

from alembic import context
from gateway.audit.infrastructure.model.audit_event import AUDIT_EVENTS_TABLE
from gateway.settings import get_settings
from shared_kernel.clickhouse import (
    CLICKHOUSE_METADATA,
    dispose_clickhouse_engine,
    get_clickhouse_engine,
)

config = context.config


def _use_short_year_revision_names() -> None:
    """Render revision filenames with a two-digit year."""
    script = context.script
    original_rev_path = script._rev_path

    def short_year_rev_path(
        path: str | Path, rev_id: str, message: str | None, create_date
    ) -> Path:
        generated = original_rev_path(path, rev_id, message, create_date)
        long_date = create_date.strftime("%Y%m%d_")
        short_date = create_date.strftime("%y%m%d_")
        if generated.name.startswith(long_date):
            return generated.with_name(short_date + generated.name[len(long_date) :])
        return generated

    script._rev_path = short_year_rev_path


_use_short_year_revision_names()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings().clickhouse
engine = get_clickhouse_engine(settings)
target_metadata = CLICKHOUSE_METADATA
assert AUDIT_EVENTS_TABLE.metadata is target_metadata


def _configure(*, connection: Connection | None = None, url=None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=clickhouse_alembic.include_object,
        process_revision_directives=clickhouse_alembic.clickhouse_writer,
    )


def run_migrations_offline() -> None:
    """Emit ClickHouse migrations without opening a connection."""
    _configure(url=engine.url)
    context.run_migrations()


def run_migrations_online() -> None:
    """Run ClickHouse migrations without a migration-wide transaction."""
    try:
        with engine.connect() as connection:
            _configure(connection=connection)
            context.run_migrations()
    finally:
        dispose_clickhouse_engine()


if context.is_offline_mode():
    try:
        run_migrations_offline()
    finally:
        dispose_clickhouse_engine()
else:
    run_migrations_online()
