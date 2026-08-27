"""ClickHouse audit event table."""

from clickhouse_connect.cc_sqlalchemy import types
from sqlalchemy import Column, Table

from shared_kernel.clickhouse import CLICKHOUSE_METADATA

AUDIT_EVENTS_TABLE = Table(
    "audit_events",
    CLICKHOUSE_METADATA,
    Column("id", types.String()),
    Column("created_at", types.DateTime64(3)),
    Column("request_id", types.String()),
    Column("api_key_id", types.String()),
    Column("app_name", types.LowCardinality(types.String())),
    Column("guardrail", types.LowCardinality(types.String())),
    Column("guardrail_version", types.UInt32()),
    Column("mode", types.LowCardinality(types.String())),
    Column("action", types.LowCardinality(types.String())),
    Column("checkpoint", types.LowCardinality(types.String())),
    Column("checks_fired", types.Array(types.LowCardinality(types.String()))),
    Column("verdicts", types.String()),
    Column("tier_reached", types.LowCardinality(types.String())),
    Column("tainted", types.UInt8()),
    Column("latency_ms", types.Float32()),
    Column("model", types.LowCardinality(types.String())),
    Column("prompt_tokens", types.UInt32()),
    Column("completion_tokens", types.UInt32()),
)

__all__ = ["AUDIT_EVENTS_TABLE"]
