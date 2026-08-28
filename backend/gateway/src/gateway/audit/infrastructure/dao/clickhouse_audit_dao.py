import asyncio
import datetime as dt
from collections.abc import Sequence

import orjson
from clickhouse_connect.cc_sqlalchemy import types
from sqlalchemy import and_, bindparam, func, literal, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, load_only, sessionmaker
from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement

from gateway.audit.application.dao.audit_dao import AuditCursor, AuditFilter
from gateway.audit.application.result.audit_result import (
    AuditActionTrendPoint,
    AuditCheckCount,
    AuditCheckpointCount,
    AuditEventDetail,
    AuditEventSummary,
    AuditInsights,
    AuditSummary,
)
from gateway.audit.infrastructure.model.audit_event import AuditEventModel

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
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

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
                AuditEventModel,
                _effective_action().label("effective_action"),
            )
            .options(
                load_only(
                    AuditEventModel.id,
                    AuditEventModel.created_at,
                    AuditEventModel.app_name,
                    AuditEventModel.guardrail,
                    AuditEventModel.guardrail_version,
                    AuditEventModel.mode,
                    AuditEventModel.checkpoint,
                    AuditEventModel.checks_fired,
                    AuditEventModel.tier_reached,
                    AuditEventModel.tainted,
                    AuditEventModel.latency_ms,
                    AuditEventModel.model,
                )
            )
            .where(*clauses)
            .order_by(AuditEventModel.created_at.desc(), AuditEventModel.id.desc())
            .limit(bindparam("fetch_limit", type_=types.UInt16()))
        )
        rows = await asyncio.to_thread(self._execute, statement, parameters)
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = [_summary(model, effective_action) for model, effective_action in page_rows]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1][0]
            next_cursor = AuditCursor(created_at=last.created_at, event_id=last.id)
        return items, next_cursor

    async def get_event(self, event_id: str) -> AuditEventDetail | None:
        statement = (
            select(
                AuditEventModel,
                _effective_action().label("effective_action"),
            )
            .where(AuditEventModel.id == bindparam("event_id", type_=types.String()))
            .limit(1)
        )
        rows = await asyncio.to_thread(self._execute, statement, {"event_id": event_id})
        if not rows:
            return None
        model, effective_action = rows[0]
        summary = _summary(model, effective_action)
        return AuditEventDetail(
            **summary.model_dump(),
            request_id=model.request_id,
            api_key_id=model.api_key_id,
            verdicts=orjson.loads(model.verdicts),
            prompt_tokens=model.prompt_tokens,
            completion_tokens=model.completion_tokens,
            content_fingerprint=model.content_fingerprint,
            excerpt=model.excerpt,
            input_body=model.input_body,
            output_body=model.output_body,
            tool_calls_body=model.tool_calls_body,
        )

    async def summary(self, audit_filter: AuditFilter) -> AuditSummary:
        clauses, parameters = _where(audit_filter)
        filtered = (
            select(
                _effective_action().label("effective_action"),
                AuditEventModel.latency_ms,
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
        rows = await asyncio.to_thread(self._execute, statement, parameters)
        row = rows[0]._mapping
        counts = {
            str(action): int(count) for action, count in (row["counts_by_action"] or {}).items()
        }
        return AuditSummary(
            counts_by_action=dict(sorted(counts.items())),
            latency_p50=float(row["latency_p50"]),
            latency_p95=float(row["latency_p95"]),
            total=int(row["total"]),
        )

    async def insights(
        self,
        audit_filter: AuditFilter,
        *,
        bucket_seconds: int,
        top_n: int,
    ) -> AuditInsights:
        clauses, parameters = _where(audit_filter)
        check_statement = _check_ranking_statement(clauses)
        trend_statement = _action_trend_statement(clauses)
        checkpoint_statement = _checkpoint_statement(clauses)
        check_rows, trend_rows, checkpoint_rows = await asyncio.to_thread(
            self._execute_insights,
            check_statement,
            {**parameters, "top_n": top_n},
            trend_statement,
            {**parameters, "bucket_seconds": bucket_seconds},
            checkpoint_statement,
            parameters,
        )
        return AuditInsights(
            from_at=_as_utc(audit_filter.from_at),
            to_at=_as_utc(audit_filter.to_at),
            bucket_seconds=bucket_seconds,
            checks=[
                AuditCheckCount(check=str(row._mapping["check"]), count=int(row._mapping["count"]))
                for row in check_rows
            ],
            action_trend=[
                AuditActionTrendPoint(
                    bucket=_as_utc(row._mapping["bucket"]),
                    action=str(row._mapping["action"]),
                    count=int(row._mapping["count"]),
                )
                for row in trend_rows
            ],
            checkpoints=[
                AuditCheckpointCount(
                    checkpoint=str(row._mapping["checkpoint"]),
                    count=int(row._mapping["count"]),
                )
                for row in checkpoint_rows
            ],
        )

    def _execute(self, statement: Select, parameters: dict[str, object]) -> Sequence[Row]:
        with self._session_factory() as session:
            return session.execute(statement, parameters).all()

    def _execute_insights(
        self,
        check_statement: Select,
        check_parameters: dict[str, object],
        trend_statement: Select,
        trend_parameters: dict[str, object],
        checkpoint_statement: Select,
        checkpoint_parameters: dict[str, object],
    ) -> tuple[Sequence[Row], Sequence[Row], Sequence[Row]]:
        with self._session_factory() as session:
            return (
                session.execute(check_statement, check_parameters).all(),
                session.execute(trend_statement, trend_parameters).all(),
                session.execute(checkpoint_statement, checkpoint_parameters).all(),
            )


def _effective_action() -> ColumnElement[str]:
    return _IF(
        and_(
            AuditEventModel.action == literal("allow"),
            func.JSONExtractBool(
                AuditEventModel.verdicts,
                literal("masked"),
                type_=types.UInt8(),
            ),
        ),
        literal("mask"),
        AuditEventModel.action,
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


def _check_ranking_statement(clauses: list[ColumnElement[bool]]) -> Select:
    filtered = (
        select(AuditEventModel.checks_fired).where(*clauses).subquery("filtered_audit_checks")
    )
    expanded = select(
        func.arrayJoin(filtered.c.checks_fired, type_=types.String()).label("check")
    ).subquery("expanded_audit_checks")
    count = func.toUInt64(func.count(), type_=types.UInt64()).label("count")
    return (
        select(expanded.c.check, count)
        .where(expanded.c.check != literal(""))
        .group_by(expanded.c.check)
        .order_by(count.desc(), expanded.c.check.asc())
        .limit(bindparam("top_n", type_=types.UInt16()))
    )


def _action_trend_statement(clauses: list[ColumnElement[bool]]) -> Select:
    filtered = (
        select(
            AuditEventModel.created_at,
            _effective_action().label("action"),
        )
        .where(*clauses)
        .subquery("filtered_audit_actions")
    )
    interval = func.toIntervalSecond(
        bindparam("bucket_seconds", type_=types.UInt32()),
        type_=types.Int64(),
    )
    bucket = func.toStartOfInterval(
        filtered.c.created_at,
        interval,
        type_=types.DateTime64(3),
    ).label("bucket")
    count = func.toUInt64(func.count(), type_=types.UInt64()).label("count")
    return (
        select(bucket, filtered.c.action, count)
        .group_by(bucket, filtered.c.action)
        .order_by(bucket.asc(), filtered.c.action.asc())
    )


def _checkpoint_statement(clauses: list[ColumnElement[bool]]) -> Select:
    filtered = (
        select(AuditEventModel.checkpoint).where(*clauses).subquery("filtered_audit_checkpoints")
    )
    count = func.toUInt64(func.count(), type_=types.UInt64()).label("count")
    return (
        select(filtered.c.checkpoint, count)
        .where(filtered.c.checkpoint != literal(""))
        .group_by(filtered.c.checkpoint)
        .order_by(count.desc(), filtered.c.checkpoint.asc())
    )


def _summary(model: AuditEventModel, effective_action: str) -> AuditEventSummary:
    return AuditEventSummary(
        id=model.id,
        created_at=_as_utc(model.created_at),
        app_name=model.app_name,
        guardrail=model.guardrail,
        guardrail_version=model.guardrail_version,
        mode=model.mode,
        action=effective_action,
        checkpoint=model.checkpoint,
        checks_fired=list(model.checks_fired),
        tier_reached=model.tier_reached,
        tainted=bool(model.tainted),
        latency_ms=float(model.latency_ms),
        model=model.model,
    )


def _where(
    audit_filter: AuditFilter, *, cursor: AuditCursor | None = None
) -> tuple[list[ColumnElement[bool]], dict[str, object]]:
    clauses: list[ColumnElement[bool]] = []
    parameters: dict[str, object] = {}
    fields = {
        "app_name": (AuditEventModel.app_name, audit_filter.app_name),
        "guardrail": (AuditEventModel.guardrail, audit_filter.guardrail),
        "checkpoint": (AuditEventModel.checkpoint, audit_filter.checkpoint),
        "mode": (AuditEventModel.mode, audit_filter.mode),
    }
    for name, (column, value) in fields.items():
        if value is not None:
            clauses.append(column == bindparam(name, type_=types.String()))
            parameters[name] = value
    if audit_filter.action is not None:
        clauses.append(_effective_action() == bindparam("effective_action", type_=types.String()))
        parameters["effective_action"] = audit_filter.action
    if audit_filter.tainted is not None:
        clauses.append(AuditEventModel.tainted == bindparam("tainted", type_=types.UInt8()))
        parameters["tainted"] = int(audit_filter.tainted)
    if audit_filter.check is not None:
        clauses.append(
            func.has(
                AuditEventModel.checks_fired,
                bindparam("check", type_=types.String()),
                type_=types.UInt8(),
            )
            == literal(1)
        )
        parameters["check"] = audit_filter.check
    clauses.append(AuditEventModel.created_at >= bindparam("from_at", type_=types.DateTime64(3)))
    parameters["from_at"] = _clickhouse_datetime(audit_filter.from_at)
    clauses.append(AuditEventModel.created_at <= bindparam("to_at", type_=types.DateTime64(3)))
    parameters["to_at"] = _clickhouse_datetime(audit_filter.to_at)
    if cursor is not None:
        cursor_created_at = bindparam("cursor_created_at", type_=types.DateTime64(3))
        clauses.append(
            or_(
                AuditEventModel.created_at < cursor_created_at,
                and_(
                    AuditEventModel.created_at == cursor_created_at,
                    AuditEventModel.id < bindparam("cursor_id", type_=types.String()),
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
