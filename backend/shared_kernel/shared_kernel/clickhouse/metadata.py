"""SQLAlchemy Core metadata for ClickHouse tables."""

from sqlalchemy import MetaData

CLICKHOUSE_METADATA = MetaData()

__all__ = ["CLICKHOUSE_METADATA"]
