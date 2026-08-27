import asyncio
import datetime as dt

import orjson
from clickhouse_connect.cc_sqlalchemy import types
from clickhouse_connect.cc_sqlalchemy.dialect import ClickHouseDialect
from sqlalchemy import and_, bindparam, func, literal, or_, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement

from gateway.audit.application.dao.audit_dao import AuditCursor, AuditFilter
from gateway.audit.application.result.audit_result import (
    AuditEventDetail,
    AuditEventSummary,
    AuditSummary,
)
from gateway.audit.infrastructure.model.audit_event import AUDIT_EVENTS_TABLE

_DIALECT = ClickHouseDialect(server_side_params=True)
_IF = getattr(func, "if")


class _QuantileTDigest(FunctionElement):
    """ClickHouse parameterized quantileTDigest aggregate."""

    type = types.Float64()
    inherit_cache = True


@compiles(_QuantileTDigest, "clickhousedb")
def _compile_quantile_tdigest(element: _QuantileTDigest, compiler: SQLCompiler, **kwargs) -> str:
    quantile, value = list(element.clauses)
    return (
        f"quantileTDigest({compiler.process(quantile, **kwargs)})"
        f"({compiler.process(value, **kwargs)})"
    )


class ClickHouseAuditDao:
    def __init__(self, client) -> None:
        self._client = client

    async def list_events(
        self,
        audit_filter: AuditFilter,
        *,
        limit: int,
        cursor: AuditCursor | None,
    ) -> tuple[list[AuditEventSummary], AuditCursor | None]:
        clauses, parameters = _where(audit_filter, cursor=cursor)
        parameters["fetch_limit"] = limit + 1
        statement = (
            select(
                AUDIT_EVENTS_TABLE.c.id,
                AUDIT_EVENTS_TABLE.c.created_at,
                AUDIT_EVENTS_TABLE.c.app_name,
                AUDIT_EVENTS_TABLE.c.guardrail,
                AUDIT_EVENTS_TABLE.c.guardrail_version,
                AUDIT_EVENTS_TABLE.c.mode,
                _effective_action().label("effective_action"),
                AUDIT_EVENTS_TABLE.c.checkpoint,
                AUDIT_EVENTS_TABLE.c.checks_fired,
                AUDIT_EVENTS_TABLE.c.tier_reached,
                AUDIT_EVENTS_TABLE.c.tainted,
                AUDIT_EVENTS_TABLE.c.latency_ms,
                AUDIT_EVENTS_TABLE.c.model,
            )
            .where(*clauses)
            .order_by(AUDIT_EVENTS_TABLE.c.created_at.desc(), AUDIT_EVENTS_TABLE.c.id.desc())
            .limit(bindparam("fetch_limit", type_=types.UInt16()))
        )
        rows = await asyncio.to_thread(self._query, statement, parameters)
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = [_summary(row) for row in page_rows]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = AuditCursor(created_at=last["created_at"], event_id=last["id"])
        return items, next_cursor

    async def get_event(self, event_id: str) -> AuditEventDetail | None:
        statement = (
            select(
                AUDIT_EVENTS_TABLE.c.id,
                AUDIT_EVENTS_TABLE.c.created_at,
                AUDIT_EVENTS_TABLE.c.request_id,
                AUDIT_EVENTS_TABLE.c.api_key_id,
                AUDIT_EVENTS_TABLE.c.app_name,
                AUDIT_EVENTS_TABLE.c.guardrail,
                AUDIT_EVENTS_TABLE.c.guardrail_version,
                AUDIT_EVENTS_TABLE.c.mode,
                _effective_action().label("effective_action"),
                AUDIT_EVENTS_TABLE.c.checkpoint,
                AUDIT_EVENTS_TABLE.c.checks_fired,
                AUDIT_EVENTS_TABLE.c.verdicts,
                AUDIT_EVENTS_TABLE.c.tier_reached,
                AUDIT_EVENTS_TABLE.c.tainted,
                AUDIT_EVENTS_TABLE.c.latency_ms,
                AUDIT_EVENTS_TABLE.c.model,
                AUDIT_EVENTS_TABLE.c.prompt_tokens,
                AUDIT_EVENTS_TABLE.c.completion_tokens,
            )
            .where(AUDIT_EVENTS_TABLE.c.id == bindparam("event_id", type_=types.String()))
            .limit(1)
        )
        rows = await asyncio.to_thread(self._query, statement, {"event_id": event_id})
        if not rows:
            return None
        row = rows[0]
        summary = _summary(row)
        return AuditEventDetail(
            **summary.model_dump(),
            request_id=row["request_id"],
            api_key_id=row["api_key_id"],
            verdicts=orjson.loads(row["verdicts"]),
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
        )

    async def summary(self, audit_filter: AuditFilter) -> AuditSummary:
        clauses, parameters = _where(audit_filter)
        filtered = (
            select(
                _effective_action().label("effective_action"),
                AUDIT_EVENTS_TABLE.c.latency_ms,
            )
            .where(*clauses)
            .subquery()
        )
        total = func.count()
        statement = select(
            func.map(
                literal("allow"),
                _count_action(filtered.c.effective_action, "allow"),
                literal("mask"),
                _count_action(filtered.c.effective_action, "mask"),
                literal("blocked"),
                _count_action(filtered.c.effective_action, "blocked"),
                literal("approval_required"),
                _count_action(filtered.c.effective_action, "approval_required"),
                type_=types.Map(types.String(), types.UInt64()),
            ).label("counts_by_action"),
            total.label("total"),
            _latency_quantile(total, filtered.c.latency_ms, 0.5).label("latency_p50"),
            _latency_quantile(total, filtered.c.latency_ms, 0.95).label("latency_p95"),
        ).select_from(filtered)
        rows = await asyncio.to_thread(self._query, statement, parameters)
        row = rows[0]
        counts = {
            str(action): int(count) for action, count in (row["counts_by_action"] or {}).items()
        }
        return AuditSummary(
            counts_by_action=dict(sorted(counts.items())),
            latency_p50=float(row["latency_p50"]),
            latency_p95=float(row["latency_p95"]),
            total=int(row["total"]),
        )

    def _query(self, statement: Select, parameters: dict[str, object]) -> list[dict]:
        compiled = statement.params(**parameters).compile(dialect=_DIALECT)
        result = self._client.query(str(compiled), parameters=compiled.params)
        return list(result.named_results())


def _effective_action() -> ColumnElement[str]:
    return _IF(
        and_(
            AUDIT_EVENTS_TABLE.c.action == literal("allow"),
            func.JSONExtractBool(
                AUDIT_EVENTS_TABLE.c.verdicts,
                literal("masked"),
                type_=types.UInt8(),
            ),
        ),
        literal("mask"),
        AUDIT_EVENTS_TABLE.c.action,
        type_=types.String(),
    )


def _count_action(action_column: ColumnElement[str], action: str) -> ColumnElement[int]:
    return func.toUInt64(
        func.countIf(action_column == literal(action)),
        type_=types.UInt64(),
    )


def _latency_quantile(
    total: ColumnElement[int], latency_column: ColumnElement[float], quantile: float
) -> ColumnElement[float]:
    return _IF(
        total == literal(0),
        literal(0.0),
        _QuantileTDigest(literal(quantile), latency_column),
        type_=types.Float64(),
    )


def _summary(row: dict) -> AuditEventSummary:
    return AuditEventSummary(
        id=row["id"],
        created_at=_as_utc(row["created_at"]),
        app_name=row["app_name"],
        guardrail=row["guardrail"],
        guardrail_version=row["guardrail_version"],
        mode=row["mode"],
        action=row["effective_action"],
        checkpoint=row["checkpoint"],
        checks_fired=list(row["checks_fired"]),
        tier_reached=row["tier_reached"],
        tainted=bool(row["tainted"]),
        latency_ms=float(row["latency_ms"]),
        model=row["model"],
    )


def _where(
    audit_filter: AuditFilter, *, cursor: AuditCursor | None = None
) -> tuple[list[ColumnElement[bool]], dict[str, object]]:
    clauses: list[ColumnElement[bool]] = []
    parameters: dict[str, object] = {}
    fields = {
        "app_name": (AUDIT_EVENTS_TABLE.c.app_name, audit_filter.app_name),
        "guardrail": (AUDIT_EVENTS_TABLE.c.guardrail, audit_filter.guardrail),
        "checkpoint": (AUDIT_EVENTS_TABLE.c.checkpoint, audit_filter.checkpoint),
        "mode": (AUDIT_EVENTS_TABLE.c.mode, audit_filter.mode),
    }
    for name, (column, value) in fields.items():
        if value is not None:
            clauses.append(column == bindparam(name, type_=types.String()))
            parameters[name] = value
    if audit_filter.action is not None:
        clauses.append(_effective_action() == bindparam("effective_action", type_=types.String()))
        parameters["effective_action"] = audit_filter.action
    if audit_filter.tainted is not None:
        clauses.append(AUDIT_EVENTS_TABLE.c.tainted == bindparam("tainted", type_=types.UInt8()))
        parameters["tainted"] = int(audit_filter.tainted)
    if audit_filter.from_at is not None:
        clauses.append(
            AUDIT_EVENTS_TABLE.c.created_at >= bindparam("from_at", type_=types.DateTime64(3))
        )
        parameters["from_at"] = _clickhouse_datetime(audit_filter.from_at)
    if audit_filter.to_at is not None:
        clauses.append(
            AUDIT_EVENTS_TABLE.c.created_at <= bindparam("to_at", type_=types.DateTime64(3))
        )
        parameters["to_at"] = _clickhouse_datetime(audit_filter.to_at)
    if cursor is not None:
        cursor_created_at = bindparam("cursor_created_at", type_=types.DateTime64(3))
        clauses.append(
            or_(
                AUDIT_EVENTS_TABLE.c.created_at < cursor_created_at,
                and_(
                    AUDIT_EVENTS_TABLE.c.created_at == cursor_created_at,
                    AUDIT_EVENTS_TABLE.c.id < bindparam("cursor_id", type_=types.String()),
                ),
            )
        )
        parameters["cursor_created_at"] = _clickhouse_datetime(cursor.created_at)
        parameters["cursor_id"] = cursor.event_id
    return clauses, parameters


def _clickhouse_datetime(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.UTC).replace(tzinfo=None)


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)
