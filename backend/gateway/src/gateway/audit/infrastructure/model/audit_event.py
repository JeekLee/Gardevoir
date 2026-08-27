"""ClickHouse audit event table."""

import datetime as dt

from clickhouse_connect.cc_sqlalchemy import engines, types
from sqlalchemy import column, func
from sqlalchemy.orm import Mapped, mapped_column

from shared_kernel.clickhouse import CHBase


class AuditEventModel(CHBase):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(types.String(), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(types.DateTime64(3))
    request_id: Mapped[str] = mapped_column(types.String())
    api_key_id: Mapped[str] = mapped_column(types.String())
    app_name: Mapped[str] = mapped_column(types.LowCardinality(types.String()))
    guardrail: Mapped[str] = mapped_column(types.LowCardinality(types.String()))
    guardrail_version: Mapped[int] = mapped_column(types.UInt32())
    mode: Mapped[str] = mapped_column(types.LowCardinality(types.String()))
    action: Mapped[str] = mapped_column(types.LowCardinality(types.String()))
    checkpoint: Mapped[str] = mapped_column(types.LowCardinality(types.String()))
    checks_fired: Mapped[list[str]] = mapped_column(
        types.Array(types.LowCardinality(types.String()))
    )
    verdicts: Mapped[str] = mapped_column(types.String())
    tier_reached: Mapped[str] = mapped_column(types.LowCardinality(types.String()))
    tainted: Mapped[int] = mapped_column(types.UInt8())
    latency_ms: Mapped[float] = mapped_column(types.Float32())
    model: Mapped[str] = mapped_column(types.LowCardinality(types.String()))
    prompt_tokens: Mapped[int] = mapped_column(types.UInt32())
    completion_tokens: Mapped[int] = mapped_column(types.UInt32())
    content_fingerprint: Mapped[str] = mapped_column(types.String())
    excerpt: Mapped[str] = mapped_column(types.String())
    input_body: Mapped[str] = mapped_column(types.String())
    output_body: Mapped[str] = mapped_column(types.String())
    tool_calls_body: Mapped[str] = mapped_column(types.String())

    __table_args__ = (
        engines.MergeTree(
            order_by=["app_name", "created_at", "id"],
            partition_by=func.toYYYYMM(column("created_at")),
        ),
    )


AUDIT_EVENTS_TABLE = AuditEventModel.__table__

__all__ = ["AUDIT_EVENTS_TABLE", "AuditEventModel"]
