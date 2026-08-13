"""Audit sink: queue in front, batched ClickHouse insert behind.

응답 경로를 절대 막지 않는다(§10). 배치는 ClickHouse 의 요구사항이기도 하다 —
작은 삽입을 자주 하면 파트가 과도하게 생긴다.

컬럼 순서와 행 변환은 여기가 소유한다. AuditEvent 는 저장소를 모른다.
"""

import asyncio
import contextlib
import logging

from gateway.application.audit.audit_event import AuditEvent

logger = logging.getLogger(__name__)

#: 감사의 존재 이유인 이벤트들. 큐가 꽉 차도 버리지 않는다 (§10).
CRITICAL_ACTIONS = frozenset({"blocked", "approval_required"})

#: clickhouse/001_audit_events.sql 의 컬럼 순서와 일치해야 한다.
#: 어긋나면 삽입이 조용히 엉뚱한 열에 들어간다.
AUDIT_COLUMNS = [
    "id",
    "created_at",
    "request_id",
    "api_key_id",
    "app_name",
    "guardrail",
    "guardrail_version",
    "mode",
    "action",
    "checkpoint",
    "checks_fired",
    "verdicts",
    "tier_reached",
    "tainted",
    "latency_ms",
    "model",
    "prompt_tokens",
    "completion_tokens",
]

_TABLE = "audit_events"


def _to_row(event: AuditEvent) -> list:
    """Row ordered to match AUDIT_COLUMNS.

    created_at stays a datetime. Passing unix seconds as an int makes ClickHouse
    read them as milliseconds and store 1970 dates with no error at all (§11.10).
    """
    return [
        event.id,
        event.created_at,
        event.request_id,
        event.api_key_id,
        event.app_name,
        event.guardrail,
        event.guardrail_version,
        event.mode,
        event.action,
        str(event.checkpoint),
        list(event.checks_fired),
        event.verdicts,
        event.tier_reached,
        1 if event.tainted else 0,
        event.latency_ms,
        event.model,
        event.prompt_tokens,
        event.completion_tokens,
    ]


class ClickHouseAuditSink:
    def __init__(
        self, client, *, batch_size: int, flush_interval_s: float, queue_maxsize: int
    ) -> None:
        self._client = client
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._queue: asyncio.Queue[AuditEvent] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task | None = None
        self.written = 0
        self.dropped = 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the background task, then drain what is left. Idempotent."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        while batch := self._drain(self._batch_size):
            await asyncio.to_thread(self._flush, batch)

    async def submit(self, event: AuditEvent) -> None:
        """Enqueue without blocking. Never raises into the response path."""
        try:
            self._queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass

        if event.action in CRITICAL_ACTIONS:
            # 임계 이벤트는 버리지 않는다. 이 요청 하나는 삽입을 기다리지만
            # 이벤트 루프는 막지 않는다.
            await asyncio.to_thread(self._flush, [event])
        else:
            self.dropped += 1
            logger.warning("audit queue full; dropped %s event", event.action)

    async def _run(self) -> None:
        """Block on the queue, then take as much as the batch allows.

        큐가 비어 있으면 flush_interval_s 만큼 기다리고, 이벤트가 하나라도
        들어오면 즉시 그것과 함께 쌓인 것을 모아 삽입한다. 한산할 때는 지연이
        낮고, 바쁠 때는 자연히 배치가 커진다.

        _stopping 플래그를 보지 않고 무한 루프를 돈다 — stop() 이 cancel() 로
        끝내고 남은 것을 직접 비운다. 취소 지점이 wait_for 한 곳으로 모여서
        배치가 반쯤 삽입된 상태로 죽는 경우가 없다.
        """
        while True:
            try:
                first = await asyncio.wait_for(self._queue.get(), timeout=self._flush_interval_s)
            except TimeoutError:
                continue
            batch = [first, *self._drain(self._batch_size - 1)]
            await asyncio.to_thread(self._flush, batch)

    def _drain(self, limit: int) -> list[AuditEvent]:
        batch: list[AuditEvent] = []
        while len(batch) < limit:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    def _flush(self, batch: list[AuditEvent]) -> None:
        """Synchronous insert. Always call via asyncio.to_thread.

        clickhouse-connect 의 클라이언트는 동기이므로 이벤트 루프에서 직접
        호출하면 삽입이 끝날 때까지 프록시 전체가 멈춘다. 100행 삽입이 5~20ms
        인데 그것이 진행 중인 모든 요청에 얹힌다.
        """
        if not batch:
            return
        try:
            self._client.insert(_TABLE, [_to_row(e) for e in batch], column_names=AUDIT_COLUMNS)
            self.written += len(batch)
        except Exception:
            self.dropped += len(batch)
            logger.exception("audit insert failed; dropped %d events", len(batch))
