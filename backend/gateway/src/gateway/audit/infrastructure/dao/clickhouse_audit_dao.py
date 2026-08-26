import asyncio
import datetime as dt

import orjson

from gateway.audit.application.dao.audit_dao import AuditCursor, AuditFilter
from gateway.audit.application.result.audit_result import (
    AuditEventDetail,
    AuditEventSummary,
    AuditSummary,
)

_TABLE = "audit_events"
_EFFECTIVE_ACTION = "if(action = 'allow' AND JSONExtractBool(verdicts, 'masked'), 'mask', action)"


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
        where, parameters = _where(audit_filter, cursor=cursor)
        parameters["fetch_limit"] = limit + 1
        query = f"""
            SELECT
                id,
                created_at,
                app_name,
                guardrail,
                guardrail_version,
                mode,
                {_EFFECTIVE_ACTION} AS effective_action,
                checkpoint,
                checks_fired,
                tier_reached,
                tainted,
                latency_ms,
                model
            FROM {_TABLE}
            WHERE {where}
            ORDER BY created_at DESC, id DESC
            LIMIT {{fetch_limit:UInt16}}
        """
        rows = await asyncio.to_thread(self._query, query, parameters)
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = [_summary(row) for row in page_rows]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = AuditCursor(created_at=last["created_at"], event_id=last["id"])
        return items, next_cursor

    async def get_event(self, event_id: str) -> AuditEventDetail | None:
        query = f"""
            SELECT
                id,
                created_at,
                request_id,
                api_key_id,
                app_name,
                guardrail,
                guardrail_version,
                mode,
                {_EFFECTIVE_ACTION} AS effective_action,
                checkpoint,
                checks_fired,
                verdicts,
                tier_reached,
                tainted,
                latency_ms,
                model,
                prompt_tokens,
                completion_tokens
            FROM {_TABLE}
            WHERE id = {{event_id:String}}
            LIMIT 1
        """
        rows = await asyncio.to_thread(self._query, query, {"event_id": event_id})
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
        where, parameters = _where(audit_filter)
        query = f"""
            SELECT
                map(
                    'allow', toUInt64(countIf(effective_action = 'allow')),
                    'mask', toUInt64(countIf(effective_action = 'mask')),
                    'blocked', toUInt64(countIf(effective_action = 'blocked')),
                    'approval_required',
                        toUInt64(countIf(effective_action = 'approval_required'))
                ) AS counts_by_action,
                count() AS total,
                if(total = 0, 0., quantileTDigest(0.5)(latency_ms)) AS latency_p50,
                if(total = 0, 0., quantileTDigest(0.95)(latency_ms)) AS latency_p95
            FROM (
                SELECT
                    {_EFFECTIVE_ACTION} AS effective_action,
                    latency_ms
                FROM {_TABLE}
                WHERE {where}
            )
        """
        rows = await asyncio.to_thread(self._query, query, parameters)
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

    def _query(self, query: str, parameters: dict) -> list[dict]:
        result = self._client.query(query, parameters=parameters)
        return list(result.named_results())


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


def _where(audit_filter: AuditFilter, *, cursor: AuditCursor | None = None) -> tuple[str, dict]:
    clauses: list[str] = []
    parameters: dict = {}
    fields = {
        "app_name": audit_filter.app_name,
        "guardrail": audit_filter.guardrail,
        "checkpoint": audit_filter.checkpoint,
        "mode": audit_filter.mode,
    }
    for field, value in fields.items():
        if value is not None:
            clauses.append(f"{field} = {{{field}:String}}")
            parameters[field] = value
    if audit_filter.action is not None:
        clauses.append(f"{_EFFECTIVE_ACTION} = {{effective_action:String}}")
        parameters["effective_action"] = audit_filter.action
    if audit_filter.tainted is not None:
        clauses.append("tainted = {tainted:UInt8}")
        parameters["tainted"] = int(audit_filter.tainted)
    if audit_filter.from_at is not None:
        clauses.append("created_at >= {from_at:DateTime64(3)}")
        parameters["from_at"] = _clickhouse_datetime(audit_filter.from_at)
    if audit_filter.to_at is not None:
        clauses.append("created_at <= {to_at:DateTime64(3)}")
        parameters["to_at"] = _clickhouse_datetime(audit_filter.to_at)
    if cursor is not None:
        clauses.append(
            "(created_at < {cursor_created_at:DateTime64(3)} OR "
            "(created_at = {cursor_created_at:DateTime64(3)} AND id < {cursor_id:String}))"
        )
        parameters["cursor_created_at"] = _clickhouse_datetime(cursor.created_at)
        parameters["cursor_id"] = cursor.event_id
    return " AND ".join(clauses) if clauses else "1", parameters


def _clickhouse_datetime(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.UTC).replace(tzinfo=None)


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)
