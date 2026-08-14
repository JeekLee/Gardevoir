"""Streaming relay — 흘리면서 검사한다 (§9).

두 성질이 반대라 처리도 다르다.

```
텍스트      ──▶ 홀드백 뒤로 흘려보냄 ──▶ 윈도우로 검사, 홀드백 안이면 치환
tool_call   ──▶ 전부 버퍼에 모음     ──▶ 완성 시 검사 → 통과/차단
```

멈추는 것은 BLOCK 뿐이다 (§9 의 표). ④ 는 아무것도 방출하지 않았으니 안 멈추고,
③ MASK 는 홀드백 안이면 치환하고 계속 흘린다.

업스트림 청크를 그대로 흘릴 수 없다 — 홀드백이 본질적으로 내용을 늦춘다. 첫 청크를
틀로 삼아 합성하고, 청크 경계가 달라져도 SDK 가 파싱하는지 §11.9 회귀로 확인한다.
"""

import logging
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

from gateway.guardrail.domain.models.guardrail import VerdictAction
from gateway.guardrail.domain.models.mode import Mode
from gateway.guardrail.inspection.application.inspector import (
    CHECKPOINT_OUTPUT,
    CHECKPOINT_TOOL_CALL,
    Inspector,
)
from gateway.guardrail.inspection.application.outcome import (
    MASK_PLACEHOLDER,
    NOT_INSPECTED,
    Inspection,
)
from gateway.guardrail.plan.domain.models.execution_plan import ExecutionPlan, Program
from gateway.proxy.application.streaming.accumulator import Accumulator
from gateway.proxy.application.streaming.holdback import Holdback
from gateway.proxy.application.streaming.sse import parse_frames, render, render_done
from gateway.proxy.contract import FINISH_CONTENT_FILTER

logger = logging.getLogger(__name__)

#: BLOCK 으로 스트림을 끊을 때 붙이는 이유. 많은 앱이 finish_reason 을 보지 않는다 (§7.3).
STOP_NOTICE = "\n\n[이 응답은 정책에 의해 중단되었습니다.]"


@dataclass(slots=True)
class RelayOutcome:
    """중계가 끝난 뒤의 판정 — 감사와 확장 객체가 읽는다."""

    output: Inspection = NOT_INSPECTED
    tool_call: Inspection = NOT_INSPECTED
    stopped: bool = False
    #: 마스킹 판정이 걸렸는데 이미 방출돼서 가릴 수 없었던 횟수 (§9 의 홀드백 0 상황).
    unmaskable: int = 0
    model: str = ""
    usage: dict = field(default_factory=dict)
    #: 우리가 실제로 쓴 시간(ms). 스트리밍은 전체 소요에서 업스트림 생성 대기를 빼는
    #: 방식으로는 계산할 수 없다 — 청크 사이의 대기가 전부 업스트림 몫이다.
    #: 그래서 검사에 들어간 구간만 직접 잰다 (§7.2: 게이트웨이가 더한 지연만).
    processing_ms: float = 0.0


class StreamRelay:
    """SSE 를 중계하면서 ③④ 를 돌린다. SSE 를 아는 것은 이 클래스뿐이다."""

    def __init__(
        self,
        *,
        inspector: Inspector | None,
        plan: ExecutionPlan | None,
        mode: Mode,
        tainted: bool,
        payload: object,
        holdback_chars: int,
        window_chars: int,
    ) -> None:
        self._inspector = inspector
        self._plan = plan
        self._mode = mode
        self._tainted = tainted
        self._payload = payload
        self._acc = Accumulator()
        self._hold = Holdback(chars=holdback_chars, window=window_chars)
        self.outcome = RelayOutcome()

    @property
    def inspects_output(self) -> bool:
        return self._program(CHECKPOINT_OUTPUT) is not None

    @property
    def inspects_tool_calls(self) -> bool:
        return self._program(CHECKPOINT_TOOL_CALL) is not None

    async def relay(self, upstream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        tail = b""
        opened = False
        async for raw in upstream:
            frames, tail = parse_frames(tail + raw)
            for frame in frames:
                if frame.is_done:
                    continue
                if not frame.is_data:
                    # 이해 못한 프레임은 그대로 흘린다.
                    yield frame.raw
                    continue

                piece = self._acc.feed(frame.payload)
                if not opened and self._is_opening(frame.payload):
                    # SDK 가 이 청크를 보고 메시지를 시작한다. 붙들 이유가 없다.
                    opened = True
                    yield frame.raw
                    continue
                if not piece:
                    # tool_call 조각·finish_reason 등은 붙들어 둔다. 끝에서 처리한다.
                    continue

                released, stop = self._advance(piece)
                if released:
                    yield self._content_frame(released)
                if stop:
                    for chunk in self._stop_frames():
                        yield chunk
                    yield render_done()
                    return

        for chunk in self._finish():
            yield chunk
        yield render_done()

    # -- 텍스트 (③) ---------------------------------------------------------

    def _advance(self, piece: str) -> tuple[str, bool]:
        """새 조각을 넣고 검사한 뒤 ``(방출할 텍스트, 멈출까)`` 를 돌려준다.

        순서가 중요하다: 버퍼에 넣고 → 검사·치환하고 → 방출한다. 방출을 먼저 하면
        치환할 기회가 사라진다.
        """
        self._hold.append(piece)
        program = self._program(CHECKPOINT_OUTPUT)
        if program is not None and self._inspect_window(program):
            return "", True
        return self._hold.release(), False

    def _inspect_window(self, program: Program) -> bool:
        """윈도우를 검사하고 치환한다. 멈춰야 하면 True."""
        assert self._inspector is not None
        started = time.perf_counter()
        try:
            return self._inspect_window_inner(program)
        finally:
            self.outcome.processing_ms += (time.perf_counter() - started) * 1000

    def _inspect_window_inner(self, program: Program) -> bool:
        assert self._inspector is not None
        text, offset = self._hold.inspection_window()
        verdict, spans = self._inspector.stream_text(
            program, text, mode=self._mode, tainted=self._tainted
        )
        self._merge_output(verdict)
        self._apply_spans(spans, offset)
        return verdict.blocked

    def _apply_spans(self, spans: list[tuple[int, int]], offset: int) -> None:
        # 뒤에서부터 치환한다 — 앞을 먼저 바꾸면 뒤 오프셋이 밀린다.
        for start, end in reversed(spans):
            if self._hold.mask(offset + start, offset + end, MASK_PLACEHOLDER):
                continue
            # 이미 방출한 구간은 되돌릴 수 없다 (§9 의 Post 패턴). 멈춰도 사용자가 본
            # 것은 지워지지 않으므로 멈추지 않고, 못 가렸다는 사실을 남긴다.
            self.outcome.unmaskable += 1
            logger.warning(
                "a mask verdict fired outside the holdback; that text was already "
                "emitted (holdback=%d chars)",
                self._hold.chars,
            )

    def _merge_output(self, verdict: Inspection) -> None:
        previous = self.outcome.output
        blocked = previous.blocked or verdict.blocked
        self.outcome.output = Inspection(
            action=VerdictAction.BLOCK if blocked else VerdictAction.ALLOW,
            tier=verdict.tier,
            checks_fired=tuple(dict.fromkeys(previous.checks_fired + verdict.checks_fired)),
            pending_model=tuple(dict.fromkeys(previous.pending_model + verdict.pending_model)),
            masked=previous.masked or verdict.masked,
            would_have=previous.would_have or verdict.would_have,
        )

    # -- 종료 ---------------------------------------------------------------

    def _finish(self) -> Iterator[bytes]:
        """남은 것을 검사하고 내보낸다.

        치환은 **flush 전에** 버퍼에서 한다. flush 한 뒤에 고치려 하면 오프셋을 두 좌표계
        사이에서 옮겨야 하고, 그 계산이 틀리면 조용히 원문이 나간다.
        """
        program = self._program(CHECKPOINT_OUTPUT)
        if program is not None and self._hold.unemitted and self._inspect_window(program):
            yield from self._stop_frames()
            return

        remaining = self._hold.flush()
        if remaining:
            yield self._content_frame(remaining)
        yield from self._tool_frames()
        self.outcome.model = self._acc.model
        self.outcome.usage = self._acc.usage

    def _tool_frames(self) -> Iterator[bytes]:
        """④ — 전부 버퍼링했으므로 아무것도 방출하지 않았다 (§9)."""
        program = self._program(CHECKPOINT_TOOL_CALL)
        started = time.perf_counter()
        if self._acc.has_tool_calls and program is not None:
            assert self._inspector is not None
            verdict = self._inspector.tool_call(
                self._plan,
                self._acc.as_completion(),
                self._payload,
                mode=self._mode,
                tainted=self._tainted,
            )
            self.outcome.tool_call = verdict
            self.outcome.processing_ms += (time.perf_counter() - started) * 1000
            if verdict.blocked:
                yield from self._stop_frames()
                return
        elif program is not None:
            # 검사는 돌았고 대상이 없었다 — inspected 에 남아야 한다.
            self.outcome.tool_call = self._inspector.tool_call(  # type: ignore[union-attr]
                self._plan,
                self._acc.as_completion(),
                self._payload,
                mode=self._mode,
                tainted=self._tainted,
            )
            self.outcome.processing_ms += (time.perf_counter() - started) * 1000

        if self._acc.has_tool_calls:
            yield render(
                {
                    **self._acc.template,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"tool_calls": self._acc.tool_calls},
                            "finish_reason": None,
                        }
                    ],
                }
            )
        yield self._finish_frame(self._acc.finish_reason or "stop")

    def _stop_frames(self) -> Iterator[bytes]:
        """§9 의 형태: 이유 → content_filter. 확장 객체는 호출자가 붙인다."""
        self.outcome.stopped = True
        yield self._content_frame(STOP_NOTICE)
        yield self._finish_frame(FINISH_CONTENT_FILTER)

    # -- 프레임 조립 ---------------------------------------------------------

    def _content_frame(self, text: str) -> bytes:
        return render(
            {
                **self._acc.template,
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
            }
        )

    def _finish_frame(self, reason: str) -> bytes:
        return render(
            {
                **self._acc.template,
                "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
            }
        )

    def _program(self, checkpoint: str) -> Program | None:
        if self._inspector is None or self._plan is None:
            return None
        return self._plan.program_for(checkpoint)

    @staticmethod
    def _is_opening(payload: dict) -> bool:
        """role 만 있는 첫 청크. SDK 가 이것을 보고 메시지를 시작한다."""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return False
        choice = choices[0]
        if not isinstance(choice, dict):
            return False
        delta = choice.get("delta")
        return isinstance(delta, dict) and "role" in delta and not delta.get("content")


__all__ = ["STOP_NOTICE", "RelayOutcome", "StreamRelay"]
