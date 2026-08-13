"""Proxy use case.

인증된 요청을 업스트림으로 중계하면서 체크포인트를 돌린다 (§3).

```
① 입력 검사 ──막힘──▶ 400, 업스트림 호출 없음
     │
   통과
     ▼
  업스트림
     ▼
③ 출력 검사 ──막힘──▶ 200 + finish_reason=content_filter
     │
   마스킹/통과
```

**계획은 요청 시작에 한 번 잡는다** (§6). 입력을 v37, 출력을 v38 로 검사하면 판정이
앞뒤가 안 맞고 나중에 재현이 불가능해진다.
"""

import datetime as dt
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace

import orjson

from gateway.application.audit.audit_event import AuditEvent, Checkpoint, new_event_id
from gateway.application.inspection.inspector import (
    CHECKPOINT_INPUT,
    CHECKPOINT_OUTPUT,
    CHECKPOINT_TOOL_CALL,
    CHECKPOINT_TOOL_RESULT,
    Inspector,
)
from gateway.application.inspection.outcome import NOT_INSPECTED, TIER_NONE, Inspection
from gateway.application.plan.execution_plan import ExecutionPlan
from gateway.application.port.audit_sink import AuditSink
from gateway.application.port.llm_upstream import LlmUpstream
from gateway.application.service.authentication_service import AuthenticatedRequest
from gateway.contract import (
    EXTENSION_KEY,
    UNVERSIONED_GUARDRAIL,
    Action,
    Mode,
    blocked_input_body,
    blocked_output_body,
    build_extension,
    response_headers,
)

logger = logging.getLogger(__name__)

UPSTREAM_PATH = "/chat/completions"

JSON_MEDIA_TYPE = "application/json"
SSE_MEDIA_TYPE = "text/event-stream"

BLOCKED_INPUT_STATUS = 400

_SSE_PREFIX = b"data: "
_SSE_SUFFIX = b"\n\n"


def wants_stream(payload: bytes) -> bool:
    """Read the `stream` flag without failing on anything the upstream would reject."""
    body = _decode(payload)
    return bool(isinstance(body, dict) and body.get("stream"))


def _decode(payload: bytes) -> object | None:
    try:
        return orjson.loads(payload)
    except orjson.JSONDecodeError:
        return None


@dataclass(frozen=True, slots=True)
class ProxyResult:
    status_code: int
    media_type: str
    headers: dict[str, str]
    body: bytes
    audit_id: str


@dataclass(slots=True)
class ProxyStream:
    status_code: int
    media_type: str
    headers: dict[str, str]
    audit_id: str
    _chunks: AsyncIterator[bytes] = field(repr=False)

    def aiter(self) -> AsyncIterator[bytes]:
        return self._chunks


@dataclass(frozen=True, slots=True)
class _Verdicts:
    """요청 하나의 체크포인트 결과 모음."""

    plan: ExecutionPlan | None
    input: Inspection = NOT_INSPECTED
    tool_result: Inspection = NOT_INSPECTED
    output: Inspection = NOT_INSPECTED
    tool_call: Inspection = NOT_INSPECTED
    tainted: bool = False

    @property
    def guardrail_version(self) -> int:
        return self.plan.version_number if self.plan is not None else UNVERSIONED_GUARDRAIL

    @property
    def inspected(self) -> tuple[str, ...]:
        names = []
        if self.input.ran:
            names.append(CHECKPOINT_INPUT)
        if self.tool_result.ran:
            names.append(CHECKPOINT_TOOL_RESULT)
        if self.output.ran:
            names.append(CHECKPOINT_OUTPUT)
        if self.tool_call.ran:
            names.append(CHECKPOINT_TOOL_CALL)
        return tuple(names)

    @property
    def checks(self) -> tuple[str, ...]:
        return (
            self.input.checks_fired
            + self.tool_result.checks_fired
            + self.output.checks_fired
            + self.tool_call.checks_fired
        )

    @property
    def pending_model(self) -> tuple[str, ...]:
        return (
            self.input.pending_model
            + self.tool_result.pending_model
            + self.output.pending_model
            + self.tool_call.pending_model
        )

    @property
    def action(self) -> Action:
        if (
            self.input.blocked
            or self.tool_result.blocked
            or self.output.blocked
            or self.tool_call.blocked
        ):
            return Action.BLOCKED
        return Action.ALLOW

    @property
    def would_have(self) -> Action | None:
        return (
            self.input.would_have
            or self.tool_result.would_have
            or self.output.would_have
            or self.tool_call.would_have
        )

    @property
    def blocked_before_upstream(self) -> bool:
        """① 과 ② 는 업스트림 호출 전에 결론이 난다."""
        return self.input.blocked or self.tool_result.blocked

    @property
    def checkpoint(self) -> Checkpoint:
        """감사 로그에 남길 "어디서 결론이 났나"."""
        if self.input.blocked:
            return Checkpoint.INPUT
        if self.tool_result.blocked:
            return Checkpoint.TOOL_RESULT
        if self.tool_call.blocked:
            return Checkpoint.TOOL_CALL
        if self.output.blocked or self.output.masked:
            return Checkpoint.OUTPUT
        if self.input.ran:
            return Checkpoint.INPUT
        if self.tool_result.ran:
            return Checkpoint.TOOL_RESULT
        if self.output.ran:
            return Checkpoint.OUTPUT
        if self.tool_call.ran:
            return Checkpoint.TOOL_CALL
        return Checkpoint.NONE

    @property
    def tier(self) -> str:
        return (
            self.input.tier
            or self.tool_result.tier
            or self.output.tier
            or self.tool_call.tier
            or TIER_NONE
        )

    @property
    def blocked_after_upstream(self) -> bool:
        return self.output.blocked or self.tool_call.blocked

    @property
    def evidence(self) -> tuple[dict, ...]:
        return self.tool_call.evidence


class ProxyService:
    def __init__(
        self, *, upstream: LlmUpstream, audit: AuditSink, inspector: Inspector | None = None
    ) -> None:
        self._upstream = upstream
        self._audit = audit
        self._inspector = inspector

    async def complete(
        self, *, auth: AuthenticatedRequest, payload: bytes, request_id: str
    ) -> ProxyResult:
        audit_id = new_event_id()
        started = time.perf_counter()

        plan = self._plan_for(auth)
        decoded = _decode(payload)
        verdicts = self._inspect_before_upstream(plan, decoded, auth.mode)

        if verdicts.blocked_before_upstream:
            # 차단할 요청에 토큰을 쓸 이유가 없고, 오염된 데이터를 모델에 먹이지
            # 않는 것 자체가 방어다.
            return await self._blocked_input(
                auth=auth,
                audit_id=audit_id,
                request_id=request_id,
                verdicts=verdicts,
                latency_ms=self._added_latency_ms(started, 0.0),
            )

        result = await self._upstream.complete(
            base_url=auth.key.upstream_base_url,
            api_key=auth.key.upstream_api_key,
            path=UPSTREAM_PATH,
            payload=payload,
        )

        body = _decode(result.body)
        if isinstance(body, dict) and self._inspector is not None:
            verdicts = replace(
                verdicts,
                output=self._inspector.output(plan, body, mode=auth.mode, tainted=verdicts.tainted),
                tool_call=self._inspector.tool_call(
                    plan, body, decoded, mode=auth.mode, tainted=verdicts.tainted
                ),
            )

        latency_ms = self._added_latency_ms(started, result.elapsed_s)
        extension = self._extension(auth, audit_id, verdicts)

        if verdicts.blocked_after_upstream:
            # 호출 하나만 빼고 넘기면 모델의 계획이 반쯤 실행된다 — 응답 전체를 막는다.
            payload_out = blocked_output_body(extension=extension)
            model, prompt_tokens, completion_tokens = self._usage(body)
        elif isinstance(body, dict):
            body[EXTENSION_KEY] = extension
            payload_out = body
            model, prompt_tokens, completion_tokens = self._usage(body)
        else:
            # 업스트림이 객체가 아닌 것을 주면 원본을 그대로 중계한다 — 우리가 먼저
            # 터져서 응답을 잃는 것이 더 나쁘다.
            await self._submit_audit(
                auth=auth,
                audit_id=audit_id,
                request_id=request_id,
                verdicts=verdicts,
                latency_ms=latency_ms,
                model="",
                prompt_tokens=0,
                completion_tokens=0,
            )
            return ProxyResult(
                status_code=result.status_code,
                media_type=result.headers.get("content-type", JSON_MEDIA_TYPE),
                headers=self._headers(auth, audit_id, latency_ms, verdicts),
                body=result.body,
                audit_id=audit_id,
            )

        await self._submit_audit(
            auth=auth,
            audit_id=audit_id,
            request_id=request_id,
            verdicts=verdicts,
            latency_ms=latency_ms,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        return ProxyResult(
            status_code=result.status_code,
            media_type=result.headers.get("content-type", JSON_MEDIA_TYPE),
            headers=self._headers(auth, audit_id, latency_ms, verdicts),
            body=orjson.dumps(payload_out),
            audit_id=audit_id,
        )

    @asynccontextmanager
    async def stream(
        self, *, auth: AuthenticatedRequest, payload: bytes, request_id: str
    ) -> AsyncIterator[ProxyStream]:
        """Relay SSE, appending the extension object as a final chunk.

        ③ 출력 검사는 홀드백이 있어야 의미가 있고 홀드백은 Phase 4 다 (§9). 따라서
        스트리밍은 출력을 검사하지 않고, 그 사실이 ``inspected`` 에 드러난다 —
        말하지 않으면 호출자는 검사된 줄 알고 그것이 조용한 fail-open 이다.

        헤더는 본문보다 먼저 나가므로 X-Gardevoir-Action 은 입력 단계까지의 판정만
        뜻한다. 최종 판정은 마지막 청크의 gardevoir 객체에 있다 (§7.2).
        """
        audit_id = new_event_id()
        started = time.perf_counter()

        plan = self._plan_for(auth)
        verdicts = self._inspect_before_upstream(plan, _decode(payload), auth.mode)
        skipped = [
            checkpoint
            for checkpoint in (CHECKPOINT_OUTPUT, CHECKPOINT_TOOL_CALL)
            if plan is not None and plan.program_for(checkpoint) is not None
        ]
        if skipped:
            # ③ 는 홀드백이 필요하고 ④ 는 SSE 조각 누적이 필요하다. 둘 다 Phase 4 다.
            # §9 는 tool_call 버퍼링이 UX 손실 0 이라고 하므로 ④ 는 원리적으로 가능하다.
            logger.warning(
                "guardrail %r has %s program(s) but streaming cannot inspect them yet "
                "(Phase 4); reported as inspected=%s",
                auth.guardrail,
                skipped,
                list(verdicts.inspected),
            )

        if verdicts.blocked_before_upstream:
            yield await self._blocked_input_stream(
                auth=auth,
                audit_id=audit_id,
                request_id=request_id,
                verdicts=verdicts,
                latency_ms=self._added_latency_ms(started, 0.0),
            )
            return

        extension = self._extension(auth, audit_id, verdicts)
        cm = self._upstream.open_stream(
            base_url=auth.key.upstream_base_url,
            api_key=auth.key.upstream_api_key,
            path=UPSTREAM_PATH,
            payload=payload,
        )
        async with cm as upstream_stream:
            upstream_elapsed = time.perf_counter() - started

            async def chunks() -> AsyncIterator[bytes]:
                async for chunk in upstream_stream.aiter():
                    yield chunk
                yield _SSE_PREFIX + orjson.dumps({EXTENSION_KEY: extension}) + _SSE_SUFFIX

            try:
                yield ProxyStream(
                    status_code=upstream_stream.status_code,
                    media_type=upstream_stream.headers.get("content-type", SSE_MEDIA_TYPE),
                    headers=self._headers(
                        auth,
                        audit_id,
                        self._added_latency_ms(started, upstream_elapsed),
                        verdicts,
                    ),
                    audit_id=audit_id,
                    _chunks=chunks(),
                )
            finally:
                # 소비자가 터져도 감사는 남아야 한다 — 그러지 않으면 기록에 구멍이
                # 생긴다. async 제너레이터의 finally 는 가비지 컬렉션 시점에 돌 수
                # 있어 신뢰할 수 없으므로 여기에 둔다.
                await self._submit_audit(
                    auth=auth,
                    audit_id=audit_id,
                    request_id=request_id,
                    verdicts=verdicts,
                    latency_ms=self._added_latency_ms(started, upstream_elapsed),
                    model="",
                    prompt_tokens=0,
                    completion_tokens=0,
                )

    # -- 체크포인트 ----------------------------------------------------------

    def _plan_for(self, auth: AuthenticatedRequest) -> ExecutionPlan | None:
        if self._inspector is None:
            return None
        plan = self._inspector.plan_for(auth.guardrail)
        if plan is None:
            logger.warning(
                "guardrail %r has no published version; the request is not inspected",
                auth.guardrail,
            )
        return plan

    def _inspect_before_upstream(
        self, plan: ExecutionPlan | None, decoded: object, mode: Mode
    ) -> _Verdicts:
        """① 과 ② — 업스트림 호출 전에 도는 검사.

        ① 이 막으면 ② 는 돌지 않는다. 이미 결론이 났고, 감사 로그가 "어디서 걸렸나"를
        하나로 답할 수 있어야 한다.
        """
        if self._inspector is None:
            return _Verdicts(plan=plan)

        tainted = self._inspector.tainted(decoded)
        first = self._inspector.input(plan, decoded, mode=mode, tainted=tainted)
        if first.blocked:
            return _Verdicts(plan=plan, input=first, tainted=tainted)
        return _Verdicts(
            plan=plan,
            input=first,
            tool_result=self._inspector.tool_result(plan, decoded, mode=mode, tainted=tainted),
            tainted=tainted,
        )

    async def _blocked_input(
        self,
        *,
        auth: AuthenticatedRequest,
        audit_id: str,
        request_id: str,
        verdicts: _Verdicts,
        latency_ms: float,
    ) -> ProxyResult:
        extension = self._extension(auth, audit_id, verdicts)
        await self._submit_audit(
            auth=auth,
            audit_id=audit_id,
            request_id=request_id,
            verdicts=verdicts,
            latency_ms=latency_ms,
            model="",
            prompt_tokens=0,
            completion_tokens=0,
        )
        return ProxyResult(
            status_code=BLOCKED_INPUT_STATUS,
            media_type=JSON_MEDIA_TYPE,
            headers=self._headers(auth, audit_id, latency_ms, verdicts),
            body=orjson.dumps(blocked_input_body(extension=extension)),
            audit_id=audit_id,
        )

    async def _blocked_input_stream(
        self,
        *,
        auth: AuthenticatedRequest,
        audit_id: str,
        request_id: str,
        verdicts: _Verdicts,
        latency_ms: float,
    ) -> ProxyStream:
        """스트림을 열지 않았으므로 SSE 가 아니라 JSON 이다."""
        result = await self._blocked_input(
            auth=auth,
            audit_id=audit_id,
            request_id=request_id,
            verdicts=verdicts,
            latency_ms=latency_ms,
        )

        async def single() -> AsyncIterator[bytes]:
            yield result.body

        return ProxyStream(
            status_code=result.status_code,
            media_type=JSON_MEDIA_TYPE,
            headers=result.headers,
            audit_id=audit_id,
            _chunks=single(),
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _added_latency_ms(started: float, upstream_elapsed_s: float) -> float:
        """Gateway-added latency only — the upstream wait is not ours (§7.2)."""
        total = time.perf_counter() - started
        return max(0.0, total - upstream_elapsed_s) * 1000

    @staticmethod
    def _extension(auth: AuthenticatedRequest, audit_id: str, verdicts: _Verdicts) -> dict:
        would_have = verdicts.would_have
        return build_extension(
            action=verdicts.action,
            guardrail=auth.guardrail,
            guardrail_version=verdicts.guardrail_version,
            audit_id=audit_id,
            mode=auth.mode,
            inspected=verdicts.inspected,
            checks=verdicts.checks,
            dry_run_would_have=(
                {"action": str(would_have), "checks": list(verdicts.checks)}
                if would_have is not None
                else None
            ),
        )

    @staticmethod
    def _headers(
        auth: AuthenticatedRequest, audit_id: str, latency_ms: float, verdicts: _Verdicts
    ) -> dict[str, str]:
        return response_headers(
            action=verdicts.action,
            guardrail=auth.guardrail,
            guardrail_version=verdicts.guardrail_version,
            mode=auth.mode,
            audit_id=audit_id,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _usage(body: object) -> tuple[str, int, int]:
        if not isinstance(body, dict):
            return "", 0, 0
        usage = body.get("usage") or {}
        model = body.get("model") or ""
        return (
            model if isinstance(model, str) else "",
            int(usage.get("prompt_tokens") or 0) if isinstance(usage, dict) else 0,
            int(usage.get("completion_tokens") or 0) if isinstance(usage, dict) else 0,
        )

    async def _submit_audit(
        self,
        *,
        auth: AuthenticatedRequest,
        audit_id: str,
        request_id: str,
        verdicts: _Verdicts,
        latency_ms: float,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        would_have = verdicts.would_have
        await self._audit.submit(
            AuditEvent(
                id=audit_id,
                created_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
                request_id=request_id,
                api_key_id=auth.key.id,
                app_name=auth.key.name,
                guardrail=auth.guardrail,
                guardrail_version=verdicts.guardrail_version,
                mode=str(auth.mode),
                action=str(verdicts.action),
                checkpoint=verdicts.checkpoint,
                checks_fired=verdicts.checks,
                # dry-run 이 무엇을 하려 했는지 남긴다 — 그게 dry-run 의 존재 이유다.
                verdicts=orjson.dumps(
                    {
                        "would_have": str(would_have) if would_have else None,
                        "masked": verdicts.output.masked,
                        "pending_model": list(verdicts.pending_model),
                        "inspected": list(verdicts.inspected),
                        # 툴 이름과 인수 **이름** 만. 값은 남기지 않는다 (§10).
                        "evidence": list(verdicts.evidence),
                    }
                ).decode(),
                tier_reached=verdicts.tier,
                tainted=verdicts.tainted,
                latency_ms=latency_ms,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )


__all__ = [
    "BLOCKED_INPUT_STATUS",
    "JSON_MEDIA_TYPE",
    "SSE_MEDIA_TYPE",
    "UPSTREAM_PATH",
    "ProxyResult",
    "ProxyService",
    "ProxyStream",
    "wants_stream",
]
