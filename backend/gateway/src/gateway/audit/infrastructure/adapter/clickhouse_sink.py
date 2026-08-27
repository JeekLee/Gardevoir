"""Audit sink: queue in front, batched ClickHouse insert behind.

응답 경로를 절대 막지 않는다(§10). 배치는 ClickHouse 의 요구사항이기도 하다 —
작은 삽입을 자주 하면 파트가 과도하게 생긴다.

컬럼 순서와 행 변환은 여기가 소유한다. AuditEvent 는 저장소를 모른다.
"""

import asyncio
import contextlib
import logging

from gateway.audit.application.model.audit_event import AuditEvent

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

#: stop() 이 배경 루프를 깨워 정상 종료시키는 신호. cancel() 을 쓰면 to_thread
#: 안에 있던 배치가 유실된다 — to_thread 의 await 가 취소 지점이다.
_STOP = object()

#: 종료가 영구히 걸리지 않도록 두는 상한. 이 시간을 넘기면 마지막 수단으로
#: 취소하고 로그를 남긴다.
_STOP_TIMEOUT_S = 30.0


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
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task | None = None
        self._stop_seen = False
        self.written = 0
        self.dropped = 0

    async def start(self) -> None:
        self._stop_seen = False
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Drain and shut down gracefully. Idempotent.

        배경 루프를 취소하지 않는다. 취소하면 to_thread 안에 있던 배치가
        유실되고 — to_thread 의 await 가 취소 지점이다 — 종료할 때마다 감사에
        구멍이 생긴다. 대신 신호를 큐에 넣고 루프가 스스로 끝내게 한다.
        """
        task, self._task = self._task, None
        if task is not None:
            await self._queue.put(_STOP)
            try:
                await asyncio.wait_for(task, timeout=_STOP_TIMEOUT_S)
            except TimeoutError:
                logger.error("audit sink did not stop in %.0fs; cancelling", _STOP_TIMEOUT_S)
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
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

        _STOP 신호를 받으면 남은 것을 비우고 정상 종료한다 — 취소로 끝내면
        진행 중인 배치를 잃는다.
        """
        while True:
            try:
                first = await asyncio.wait_for(self._queue.get(), timeout=self._flush_interval_s)
            except TimeoutError:
                continue

            stopping = first is _STOP
            batch = [] if stopping else [first]
            batch.extend(self._drain(self._batch_size - len(batch)))
            if batch:
                await asyncio.to_thread(self._flush, batch)
            if stopping or self._stop_seen:
                return

    def _drain(self, limit: int) -> list[AuditEvent]:
        """Take up to `limit` events, remembering a stop signal rather than
        letting it into the batch.

        센티널이 배치에 섞이면 _to_row 가 터져 배치 전체가 버려진다.
        """
        batch: list[AuditEvent] = []
        while len(batch) < limit:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is _STOP:
                self._stop_seen = True
                continue
            batch.append(item)
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
