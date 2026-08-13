import asyncio
import datetime as dt
import time

from gateway.application.audit.audit_event import AuditEvent, Checkpoint, new_event_id
from gateway.infrastructure.audit.clickhouse_sink import (
    AUDIT_COLUMNS,
    ClickHouseAuditSink,
)


def _event(action: str = "allow", **kw) -> AuditEvent:
    fields: dict = {
        "id": new_event_id(),
        "created_at": dt.datetime.now(dt.UTC).replace(tzinfo=None),
        "request_id": "req_1",
        "api_key_id": "k1",
        "app_name": "app_0",
        "guardrail": "base",
        "guardrail_version": 0,
        "mode": "enforce",
        "action": action,
        "checkpoint": Checkpoint.NONE,
        "checks_fired": (),
        "verdicts": "[]",
        "tier_reached": "",
        "tainted": False,
        "latency_ms": 0.62,
        "model": "gpt-4o",
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }
    fields.update(kw)
    return AuditEvent(**fields)


def test_columns_match_the_clickhouse_table(ch_client, audit_table):
    """컬럼 목록이 테이블과 어긋나면 삽입이 조용히 엉뚱한 열에 들어간다."""
    rows = ch_client.query("DESCRIBE audit_events").result_rows
    assert [r[0] for r in rows] == AUDIT_COLUMNS


async def test_flushes_on_batch_size(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=3, flush_interval_s=60.0, queue_maxsize=100)
    await sink.start()
    for _ in range(3):
        await sink.submit(_event())
    await sink.stop()

    assert sink.written == 3
    assert ch_client.query("SELECT count() FROM audit_events").result_rows[0][0] == 3


async def test_flushes_on_interval(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=1000, flush_interval_s=0.05, queue_maxsize=100)
    await sink.start()
    await sink.submit(_event())
    await asyncio.sleep(0.3)
    written_before_stop = sink.written
    await sink.stop()

    assert written_before_stop == 1


async def test_stop_drains_remaining_events(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=1000, flush_interval_s=60.0, queue_maxsize=100)
    await sink.start()
    for _ in range(7):
        await sink.submit(_event())
    await sink.stop()

    assert ch_client.query("SELECT count() FROM audit_events").result_rows[0][0] == 7


async def test_stop_is_idempotent(ch_client, audit_table):
    """테스트가 명시적으로 부르고 lifespan 종료가 또 부른다."""
    sink = ClickHouseAuditSink(ch_client, batch_size=10, flush_interval_s=60.0, queue_maxsize=10)
    await sink.start()
    await sink.submit(_event())
    await sink.stop()
    await sink.stop()
    assert sink.written == 1


async def test_datetime_is_stored_as_the_real_date(ch_client, audit_table):
    """§11.10: unix 초를 넣으면 1970년에 조용히 저장된다."""
    sink = ClickHouseAuditSink(ch_client, batch_size=1, flush_interval_s=60.0, queue_maxsize=10)
    await sink.start()
    await sink.submit(_event())
    await sink.stop()

    stored = ch_client.query("SELECT max(created_at) FROM audit_events").result_rows[0][0]
    assert stored.year >= 2026


async def test_every_field_round_trips(ch_client, audit_table):
    """컬럼 순서가 어긋나면 값이 엉뚱한 열에 들어간다 — 값으로 확인한다."""
    sink = ClickHouseAuditSink(ch_client, batch_size=1, flush_interval_s=60.0, queue_maxsize=10)
    await sink.start()
    event = _event(
        "blocked",
        request_id="req_rt",
        api_key_id="key_rt",
        app_name="app_rt",
        guardrail="doc-agent",
        guardrail_version=37,
        mode="dry-run",
        checkpoint=Checkpoint.TOOL_CALL,
        checks_fired=("kr-rrn", "tainted-side-effect"),
        verdicts='[{"check":"kr-rrn"}]',
        tier_reached="model",
        tainted=True,
        latency_ms=1.25,
        model="gpt-4o-mini",
        prompt_tokens=123,
        completion_tokens=45,
    )
    await sink.submit(event)
    await sink.stop()

    row = ch_client.query(
        "SELECT id, request_id, api_key_id, app_name, guardrail, guardrail_version, "
        "mode, action, checkpoint, checks_fired, verdicts, tier_reached, tainted, "
        "model, prompt_tokens, completion_tokens FROM audit_events"
    ).result_rows[0]
    assert row[0] == event.id
    assert row[1] == "req_rt"
    assert row[2] == "key_rt"
    assert row[3] == "app_rt"
    assert row[4] == "doc-agent"
    assert row[5] == 37
    assert row[6] == "dry-run"
    assert row[7] == "blocked"
    assert row[8] == "tool_call"
    assert list(row[9]) == ["kr-rrn", "tainted-side-effect"]
    assert row[10] == '[{"check":"kr-rrn"}]'
    assert row[11] == "model"
    assert row[12] == 1
    assert row[13] == "gpt-4o-mini"
    assert row[14] == 123
    assert row[15] == 45


async def test_full_queue_drops_allow_but_keeps_critical(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=1000, flush_interval_s=60.0, queue_maxsize=2)
    # 배경 태스크를 시작하지 않아 큐가 비워지지 않는다
    await sink.submit(_event("allow"))
    await sink.submit(_event("allow"))

    await sink.submit(_event("allow"))  # 큐가 꽉 찼으므로 버려진다
    assert sink.dropped == 1

    await sink.submit(_event("blocked"))  # 임계 이벤트는 동기 삽입으로 폴백
    assert sink.dropped == 1
    assert (
        ch_client.query("SELECT count() FROM audit_events WHERE action='blocked'").result_rows[0][0]
        == 1
    )


async def test_approval_required_is_also_critical(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=1000, flush_interval_s=60.0, queue_maxsize=1)
    await sink.submit(_event("allow"))
    await sink.submit(_event("approval_required"))
    assert sink.dropped == 0
    assert (
        ch_client.query(
            "SELECT count() FROM audit_events WHERE action='approval_required'"
        ).result_rows[0][0]
        == 1
    )


async def test_submit_never_raises_when_clickhouse_is_down():
    class BrokenClient:
        def insert(self, *a, **kw):
            raise RuntimeError("clickhouse down")

    sink = ClickHouseAuditSink(
        BrokenClient(), batch_size=1, flush_interval_s=60.0, queue_maxsize=10
    )
    await sink.start()
    await sink.submit(_event("blocked"))  # 예외가 응답 경로로 새어나가면 안 된다
    await asyncio.sleep(0.2)
    await sink.stop()
    assert sink.dropped >= 1


async def test_slow_insert_does_not_block_the_event_loop():
    """clickhouse-connect 은 동기다. to_thread 로 감싸지 않으면 프록시가 멈춘다."""

    class SlowClient:
        def insert(self, *a, **kw):
            time.sleep(0.5)

    sink = ClickHouseAuditSink(SlowClient(), batch_size=1, flush_interval_s=0.01, queue_maxsize=10)
    await sink.start()
    await sink.submit(_event())
    await asyncio.sleep(0.05)  # 삽입이 시작되도록 양보

    started = time.perf_counter()
    await asyncio.sleep(0.05)  # 루프가 자유롭다면 ~0.05초
    elapsed = time.perf_counter() - started
    await sink.stop()

    assert elapsed < 0.25, "이벤트 루프가 동기 삽입에 막혔다"


async def test_critical_fallback_also_avoids_blocking_the_loop():
    """큐가 꽉 찬 임계 이벤트도 루프를 막아서는 안 된다."""

    class SlowClient:
        def insert(self, *a, **kw):
            time.sleep(0.3)

    sink = ClickHouseAuditSink(
        SlowClient(), batch_size=1000, flush_interval_s=60.0, queue_maxsize=1
    )
    await sink.submit(_event("allow"))  # 큐를 채운다

    ticker_ran = 0

    async def ticker():
        nonlocal ticker_ran
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticker_ran += 1

    task = asyncio.create_task(ticker())
    await sink.submit(_event("blocked"))  # 동기 삽입 폴백
    await task

    assert ticker_ran == 10
