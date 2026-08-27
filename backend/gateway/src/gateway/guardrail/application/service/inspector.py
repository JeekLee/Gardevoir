"""Run the checkpoints against a real request (§3, §4).

계획을 **요청 시작에 한 번** 잡아서 입력·출력에 같은 것을 쓴다. 입력을 v37, 출력을
v38 로 검사하면 판정이 앞뒤가 안 맞고 나중에 재현이 불가능해진다 (§6).
"""

import logging
from collections.abc import Callable

from gateway.guardrail.application.outcome import (
    MASK_PLACEHOLDER,
    NOT_INSPECTED,
    TIER_RULES,
    Inspection,
)
from gateway.guardrail.application.provenance import (
    extract_tool_calls,
    foreign_arguments,
    tool_name,
)
from gateway.guardrail.application.service.registry import PlanRegistry
from gateway.guardrail.application.text import (
    MessageTextLocation,
    extract_input_text,
    extract_input_texts,
    extract_output_texts,
    extract_tool_result_text,
    extract_tool_result_texts,
    extract_trusted_text,
    is_tainted,
    replace_message_text,
)
from gateway.guardrail.domain.executor import Subject, execute
from gateway.guardrail.domain.models.execution_plan import (
    ExecutionPlan,
    Program,
    Provenance,
)
from gateway.guardrail.domain.models.guardrail import VerdictAction
from gateway.guardrail.domain.models.mode import Mode

logger = logging.getLogger(__name__)

CHECKPOINT_INPUT = "input"
CHECKPOINT_TOOL_RESULT = "tool_result"
CHECKPOINT_OUTPUT = "output"
CHECKPOINT_TOOL_CALL = "tool_call"


class Inspector:
    def __init__(self, *, plans: PlanRegistry) -> None:
        self._plans = plans

    def plan_for(self, guardrail: str) -> ExecutionPlan | None:
        """요청 시작에 한 번 부른다. 이후 체크포인트는 이 계획을 받는다 (§6).

        발행본이 없으면 ``None`` 이다. 그때는 통과시키고 보이게 한다 — fail-closed 로
        하면 발행 안 된 가드레일 하나가 앱 전체를 세우고, 운영자는 가드레일을 떼는
        쪽으로 움직이므로 안전이 오히려 줄어든다.
        """
        return self._plans.get(guardrail)

    def input(
        self, plan: ExecutionPlan | None, payload: object, *, mode: Mode, tainted: bool = False
    ) -> Inspection:
        program = plan.program_for(CHECKPOINT_INPUT) if plan is not None else None
        if program is None:
            return NOT_INSPECTED
        subject = Subject(text=extract_input_text(payload), tainted=tainted)
        return self._run(
            program,
            subject,
            payload,
            locate_texts=extract_input_texts,
            mode=mode,
        )

    def tool_result(
        self, plan: ExecutionPlan | None, payload: object, *, mode: Mode, tainted: bool = False
    ) -> Inspection:
        """② 검사 — 툴 결과에 심긴 지시를 잡는다 (§8).

        업스트림 호출 **전** 이다. 오염된 데이터를 모델에 먹이지 않는 것이 방어다.
        """
        program = plan.program_for(CHECKPOINT_TOOL_RESULT) if plan is not None else None
        if program is None:
            return NOT_INSPECTED
        subject = Subject(text=extract_tool_result_text(payload), tainted=tainted)
        return self._run(
            program,
            subject,
            payload,
            locate_texts=extract_tool_result_texts,
            mode=mode,
        )

    @staticmethod
    def tainted(payload: object) -> bool:
        """오염 여부. 요청마다 새로 계산한다 (§7.4)."""
        return is_tainted(payload)

    def tool_call(
        self,
        plan: ExecutionPlan | None,
        body: dict,
        payload: object,
        *,
        mode: Mode,
        tainted: bool = False,
    ) -> Inspection:
        """④ 검사 — 호출마다 한 번씩 (§8 2·3단계).

        하나라도 걸리면 응답 전체를 막는다. 호출 하나만 빼고 나머지를 넘기면 모델의
        계획이 반쯤 실행되고, 앱은 남은 툴을 불러 그 결과로 다시 요청한다.

        출처 검사는 요청 본문이 필요하다 — 인수 값이 사용자 메시지에서 왔는지 툴
        결과에서 왔는지를 봐야 한다. 그래서 ``payload`` 를 함께 받는다.
        """
        program = plan.program_for(CHECKPOINT_TOOL_CALL) if plan is not None else None
        if program is None:
            return NOT_INSPECTED

        calls = extract_tool_calls(body)
        if not calls:
            return Inspection(action=VerdictAction.ALLOW, tier=TIER_RULES)

        # 출처 검사를 쓰는 프로그램일 때만 텍스트를 모은다 — 안 쓰면 비용이 0 이다.
        thresholds = [i.min_length for i in program.instructions if isinstance(i, Provenance)]
        needs_provenance = bool(thresholds)
        trusted = extract_trusted_text(payload) if needs_provenance else ""
        external = extract_tool_result_text(payload) if needs_provenance else ""
        # 노드가 여러 개면 가장 낮은 임계값을 쓴다 — 가장 엄격한 정책이 이긴다.
        min_length = min(thresholds) if thresholds else 0

        checks: list[str] = []
        pending: list[str] = []
        evidence: list[dict] = []
        blocked = False

        for call in calls:
            name = tool_name(call)
            foreign = (
                foreign_arguments(
                    tool_call=call, trusted=trusted, external=external, min_length=min_length
                )
                if needs_provenance
                else ()
            )
            result = execute(
                program,
                Subject(tainted=tainted, tool_name=name, foreign_args=foreign),
                collect_all=mode is Mode.DRY_RUN,
            )
            checks.extend(result.checks_fired)
            pending.extend(result.pending_model)
            if result.action is VerdictAction.BLOCK:
                blocked = True
                # 증거는 이름만 남긴다 — 인수 값은 감사 로그에 넣지 않는다 (§10).
                evidence.append({"tool": name, "arguments": list(foreign)})

        if blocked and mode is Mode.DRY_RUN:
            return Inspection(
                action=VerdictAction.ALLOW,
                tier=TIER_RULES,
                checks_fired=tuple(checks),
                pending_model=tuple(pending),
                would_have=VerdictAction.BLOCK,
                evidence=tuple(evidence),
            )
        return Inspection(
            action=VerdictAction.BLOCK if blocked else VerdictAction.ALLOW,
            tier=TIER_RULES,
            checks_fired=tuple(checks),
            pending_model=tuple(pending),
            evidence=tuple(evidence),
        )

    def output(
        self, plan: ExecutionPlan | None, body: dict, *, mode: Mode, tainted: bool = False
    ) -> Inspection:
        """③ 검사. MASK 가 걸리면 ``body`` 를 제자리에서 고친다."""
        program = plan.program_for(CHECKPOINT_OUTPUT) if plan is not None else None
        if program is None:
            return NOT_INSPECTED

        texts = extract_output_texts(body)
        if not texts:
            return Inspection(action=VerdictAction.ALLOW, tier=TIER_RULES)

        checks: list[str] = []
        pending: list[str] = []
        blocked = False
        masked = False
        would_mask = False

        for position, text in texts:
            result = execute(
                program,
                Subject(text=text, tainted=tainted),
                collect_all=mode is Mode.DRY_RUN,
            )
            checks.extend(result.checks_fired)
            pending.extend(result.pending_model)

            if result.action is VerdictAction.BLOCK:
                blocked = True
            elif result.action is VerdictAction.MASK:
                if mode is Mode.DRY_RUN:
                    would_mask = True
                # dry-run 에서 응답을 고치면 시험이 아니다.
                elif self._mask_choice(program, body, position, result.checks_fired):
                    masked = True

        would_have = VerdictAction.BLOCK if blocked else VerdictAction.MASK if would_mask else None
        if would_have is not None and mode is Mode.DRY_RUN:
            return Inspection(
                action=VerdictAction.ALLOW,
                tier=TIER_RULES,
                checks_fired=tuple(checks),
                pending_model=tuple(pending),
                would_have=would_have,
            )
        return Inspection(
            action=VerdictAction.BLOCK if blocked else VerdictAction.ALLOW,
            tier=TIER_RULES,
            checks_fired=tuple(checks),
            pending_model=tuple(pending),
            masked=masked,
        )

    # -- helpers ------------------------------------------------------------

    def _run(
        self,
        program: Program,
        subject: Subject,
        payload: object,
        *,
        locate_texts: Callable[[object], list[tuple[MessageTextLocation, str]]],
        mode: Mode,
    ) -> Inspection:
        result = execute(program, subject, collect_all=mode is Mode.DRY_RUN)
        blocked = result.action is VerdictAction.BLOCK

        would_have = result.action if result.action is not VerdictAction.ALLOW else None
        if would_have is not None and mode is Mode.DRY_RUN:
            return Inspection(
                action=VerdictAction.ALLOW,
                tier=TIER_RULES,
                checks_fired=result.checks_fired,
                pending_model=result.pending_model,
                would_have=would_have,
            )
        masked = result.action is VerdictAction.MASK and self._mask_request(
            program,
            payload,
            locate_texts(payload),
            result.checks_fired,
        )
        return Inspection(
            action=VerdictAction.BLOCK if blocked else VerdictAction.ALLOW,
            tier=TIER_RULES,
            checks_fired=result.checks_fired,
            pending_model=result.pending_model,
            masked=masked,
        )

    @staticmethod
    def _mask_request(
        program: Program,
        payload: object,
        texts: list[tuple[MessageTextLocation, str]],
        fired: tuple[str, ...],
    ) -> bool:
        """Replace matching spans in each request message without joining them."""
        patterns = Inspector._mask_patterns(program, fired)
        if not patterns:
            return False

        changed = False
        for location, text in texts:
            replaced = Inspector._apply(patterns, text)
            if replaced == text:
                continue
            if replace_message_text(payload, location, replaced):
                changed = True
        if not changed:
            logger.warning("a mask verdict fired but nothing matched the original text")
        return changed

    @staticmethod
    def _mask_choice(program: Program, body: dict, position: int, fired: tuple[str, ...]) -> bool:
        """Replace the matched spans in one choice's content.

        컴파일러가 MASK 판정이 extract 를 직접 읽는 regex 에만 걸리도록 보장하므로
        (``GUARDRAIL-014``), 패턴을 원본에 다시 돌리면 반드시 같은 자리를 찾는다.

        **걸린 MASK 판정이 읽는 패턴만** 돌린다. 계획의 모든 패턴을 돌리면 차단용
        패턴까지 가려서 저작자가 쓰지 않은 정책이 된다.

        하나도 못 바꿨으면 ``False`` 를 낸다 — ``masked=True`` 라고 말하면서 원문을
        그대로 내보내는 것이 조용한 fail-open 이다.
        """
        patterns = Inspector._mask_patterns(program, fired)
        if not patterns:
            return False

        message = Inspector._message_at(body, position)
        if message is None:
            return False

        content = message.get("content")
        if isinstance(content, str):
            replaced = Inspector._apply(patterns, content)
            if replaced == content:
                logger.warning("a mask verdict fired but nothing matched the original text")
                return False
            message["content"] = replaced
            return True

        if isinstance(content, list):
            # 멀티모달은 조각을 제자리에서 고친다. 문자열로 합쳐 되쓰면 응답 모양이
            # 바뀌어 SDK 가 깨진다.
            changed = False
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "text":
                    continue
                text = part.get("text")
                if not isinstance(text, str):
                    continue
                replaced = Inspector._apply(patterns, text)
                if replaced != text:
                    part["text"] = replaced
                    changed = True
            if not changed:
                logger.warning("a mask verdict fired but nothing matched the original text")
            return changed

        return False

    @staticmethod
    def _mask_patterns(program: Program, fired: tuple[str, ...]) -> list:
        """걸린 MASK 판정이 읽는 패턴만.

        계획의 모든 패턴을 돌리면 차단용 패턴까지 가려서 저작자가 쓰지 않은 정책이 된다.
        """
        slots = {slot for node_id in fired for slot in program.mask_slots.get(node_id, ())}
        return [pattern for slot, pattern in program.patterns_by_slot.items() if slot in slots]

    @staticmethod
    def mask_spans(program: Program, fired: tuple[str, ...], text: str) -> list[tuple[int, int]]:
        """가려야 할 구간. 겹치는 것은 병합한다.

        스트리밍은 치환이 아니라 **구간**이 필요하다 — 홀드백이 아직 방출 안 된
        부분에만 손댈 수 있으므로 위치를 알아야 한다.
        """
        patterns = Inspector._mask_patterns(program, fired)
        spans = sorted(
            (match.start(), match.end()) for pattern in patterns for match in pattern.finditer(text)
        )
        merged: list[tuple[int, int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def stream_text(
        self,
        program: Program,
        text: str,
        *,
        mode: Mode,
        tainted: bool = False,
    ) -> tuple[Inspection, list[tuple[int, int]]]:
        """③ 를 스트리밍 윈도우에 적용한다.

        치환을 여기서 하지 않고 **구간**을 돌려준다 — 방출 여부는 홀드백만 안다.
        """
        result = execute(
            program, Subject(text=text, tainted=tainted), collect_all=mode is Mode.DRY_RUN
        )
        blocked = result.action is VerdictAction.BLOCK
        would_have = result.action if result.action is not VerdictAction.ALLOW else None
        spans = (
            self.mask_spans(program, result.checks_fired, text)
            if result.action is VerdictAction.MASK and mode is not Mode.DRY_RUN
            else []
        )
        if would_have is not None and mode is Mode.DRY_RUN:
            return (
                Inspection(
                    action=VerdictAction.ALLOW,
                    tier=TIER_RULES,
                    checks_fired=result.checks_fired,
                    pending_model=result.pending_model,
                    would_have=would_have,
                ),
                [],
            )
        return (
            Inspection(
                action=VerdictAction.BLOCK if blocked else VerdictAction.ALLOW,
                tier=TIER_RULES,
                checks_fired=result.checks_fired,
                pending_model=result.pending_model,
                masked=bool(spans),
            ),
            spans,
        )

    @staticmethod
    def _apply(patterns: list, text: str) -> str:
        """Replace matched spans, found with ``finditer`` rather than ``sub``.

        ``re2`` 의 ``sub`` 은 비 ASCII 치환 문자열을 망가뜨린다 — 실측으로
        ``'[개인정보 삭제됨]'`` 이 모지바케로 나왔다. ``finditer`` 의 span 은 유니코드
        문자 기준으로 정확하므로 직접 잘라 붙인다. 부수적으로 치환 문자열의 백슬래시가
        그룹 참조로 해석되는 문제도 사라진다.

        여러 패턴이 겹칠 수 있으므로 span 을 모아 병합한 뒤 한 번에 만든다 — 순차
        치환하면 앞서 넣은 placeholder 안에서 다음 패턴이 걸릴 수 있다.
        """
        spans = sorted(
            (match.start(), match.end()) for pattern in patterns for match in pattern.finditer(text)
        )
        if not spans:
            return text

        merged: list[tuple[int, int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        pieces: list[str] = []
        cursor = 0
        for start, end in merged:
            pieces.append(text[cursor:start])
            pieces.append(MASK_PLACEHOLDER)
            cursor = end
        pieces.append(text[cursor:])
        return "".join(pieces)

    @staticmethod
    def _message_at(body: dict, position: int) -> dict | None:
        choices = body.get("choices")
        if not isinstance(choices, list) or position >= len(choices):
            return None
        choice = choices[position]
        if not isinstance(choice, dict):
            return None
        message = choice.get("message")
        return message if isinstance(message, dict) else None


__all__ = ["CHECKPOINT_INPUT", "CHECKPOINT_OUTPUT", "Inspector"]
