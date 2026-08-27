"""Metadata shared by ClickHouse declarative models."""

from shared_kernel.clickhouse.base import CHBase

CLICKHOUSE_METADATA = CHBase.metadata

__all__ = ["CLICKHOUSE_METADATA"]
