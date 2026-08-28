import datetime as dt
from collections.abc import Sequence
from types import SimpleNamespace

import pytest
from clickhouse_connect.cc_sqlalchemy.dialect import ClickHouseDialect
from sqlalchemy.engine import Row
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import Select

from gateway.audit.application.dao.audit_dao import AuditCursor, AuditFilter
from gateway.audit.application.result.audit_result import AuditInsights
from gateway.audit.application.service.audit_service import AuditService
from gateway.audit.infrastructure.dao.clickhouse_audit_dao import ClickHouseAuditDao
from gateway.audit.presentation.audit_router import _audit_filter


class RecordingAuditDao(ClickHouseAuditDao):
    def __init__(self) -> None:
        super().__init__(sessionmaker())
        self.calls: list[tuple[Select, dict[str, object]]] = []
        self._responses: list[Sequence[Row]] = [
            [],
            [
                SimpleNamespace(
                    _mapping={
                        "counts_by_action": {},
                        "total": 0,
                        "latency_p50": 0.0,
                        "latency_p95": 0.0,
                    }
                )
            ],
        ]

    def _execute(self, statement: Select, parameters: dict[str, object]) -> Sequence[Row]:
        self.calls.append((statement, parameters))
        return self._responses.pop(0)

    def _execute_insights(
        self,
        check_statement: Select,
        check_parameters: dict[str, object],
        trend_statement: Select,
        trend_parameters: dict[str, object],
        checkpoint_statement: Select,
        checkpoint_parameters: dict[str, object],
    ) -> tuple[Sequence[Row], Sequence[Row], Sequence[Row]]:
        self.calls.extend(
            [
                (check_statement, check_parameters),
                (trend_statement, trend_parameters),
                (checkpoint_statement, checkpoint_parameters),
            ]
        )
        return [], [], []


class StubAuditDao:
    def __init__(self) -> None:
        self.bucket_seconds: int | None = None
        self.top_n: int | None = None

    async def insights(
        self,
        audit_filter: AuditFilter,
        *,
        bucket_seconds: int,
        top_n: int,
    ) -> AuditInsights:
        self.bucket_seconds = bucket_seconds
        self.top_n = top_n
        return AuditInsights(
            from_at=audit_filter.from_at,
            to_at=audit_filter.to_at,
            bucket_seconds=bucket_seconds,
            checks=[],
            action_trend=[],
            checkpoints=[],
        )


def audit_filter(**overrides: object) -> AuditFilter:
    values = {
        "from_at": dt.datetime(2026, 8, 27, tzinfo=dt.UTC),
        "to_at": dt.datetime(2026, 8, 28, tzinfo=dt.UTC),
        "app_name": "console-smoke",
        "guardrail": "pii-mask",
        "action": "blocked",
        "checkpoint": "output",
        "mode": "enforce",
        "tainted": False,
        "check": "pii-output",
    }
    values.update(overrides)
    return AuditFilter(**values)


def compile_clickhouse(statement: Select) -> str:
    return str(statement.compile(dialect=ClickHouseDialect(server_side_params=True)))


def test_filter_defaults_to_latest_24_hours() -> None:
    """기간을 생략해도 모든 감사 조회가 무제한 이력을 읽지 않는다."""
    before = dt.datetime.now(dt.UTC)
    result = _audit_filter(
        app_name=None,
        guardrail=None,
        action=None,
        checkpoint=None,
        mode=None,
        tainted=None,
        check=None,
        from_at=None,
        to_at=None,
    )
    after = dt.datetime.now(dt.UTC)

    assert before <= result.to_at <= after
    assert result.to_at - result.from_at == dt.timedelta(hours=24)


@pytest.mark.parametrize(
    ("duration", "expected_seconds"),
    [
        (dt.timedelta(hours=24), 3_600),
        (dt.timedelta(days=7), 21_600),
        (dt.timedelta(days=30), 86_400),
    ],
)
async def test_insight_bucket_follows_period(duration: dt.timedelta, expected_seconds: int) -> None:
    """같은 데이터가 기간에 맞는 해상도로 집계돼야 추이가 뭉개지지 않는다."""
    stub = StubAuditDao()
    service = AuditService(audit_dao=stub)

    await service.insights(
        audit_filter(from_at=dt.datetime(2026, 8, 28, tzinfo=dt.UTC) - duration),
        top_n=13,
    )

    assert stub.bucket_seconds == expected_seconds
    assert stub.top_n == 13


async def test_every_query_uses_all_filters_without_selecting_bodies() -> None:
    """목록·요약·집계가 필터를 공유하고 집계 경계에서 본문을 읽지 않는다."""
    dao = RecordingAuditDao()
    filters = audit_filter()

    await dao.list_events(
        filters,
        limit=50,
        cursor=AuditCursor.decode(
            "eyJjcmVhdGVkQXQiOiIyMDI2LTA4LTI4VDAwOjAwOjAwKzAwOjAwIiwiaWQiOiIwMVRFU1QifQ"
        ),
    )
    await dao.summary(filters)
    insights = await dao.insights(filters, bucket_seconds=3_600, top_n=7)

    assert insights.checks == []
    assert insights.action_trend == []
    assert insights.checkpoints == []
    assert len(dao.calls) == 5
    for statement, parameters in dao.calls:
        sql = compile_clickhouse(statement)
        assert "{app_name:String}" in sql
        assert "{guardrail:String}" in sql
        assert "{effective_action:String}" in sql
        assert "{checkpoint:String}" in sql
        assert "{mode:String}" in sql
        assert "{tainted:UInt8}" in sql
        assert "has(`audit_events`.`checks_fired`, {check:String})" in sql
        assert "{from_at:DateTime64(3)}" in sql
        assert "{to_at:DateTime64(3)}" in sql
        assert parameters["check"] == "pii-output"
        assert "input_body" not in sql
        assert "output_body" not in sql
        assert "tool_calls_body" not in sql
        assert "excerpt" not in sql

    ranking_sql = compile_clickhouse(dao.calls[2][0])
    assert "arrayJoin" in ranking_sql
    assert "filtered_audit_checks" in ranking_sql
    assert "LIMIT {top_n:UInt16}" in ranking_sql
    assert dao.calls[2][1]["top_n"] == 7
    assert dao.calls[3][1]["bucket_seconds"] == 3_600
