"""Run a compiled program (§6).

그래프를 걷지 않는다. 고정 크기 슬롯 배열 + 직선 순회다 — 자유 DAG 를 매번 걷는
방식보다 빠르다 (§11.4).

계획은 여러 요청이 동시에 읽는 불변 객체다. 실행 상태는 전부 지역 변수로 둔다.
"""

from dataclasses import dataclass

from gateway.guardrail.domain.models.execution_plan import (
    Extract,
    ModelCheck,
    Not,
    Program,
    RegexOne,
    RegexSet,
    ToolExtract,
    Transform,
    Verdict,
)
from gateway.guardrail.domain.models.guardrail import VerdictAction, VerdictCombine

PENDING = object()
SKIPPED = object()

#: 강한 판정이 이긴다 (§4). approval_required 는 Phase 6 에서 BLOCK 아래로 들어온다.
_SEVERITY = {
    VerdictAction.ALLOW: 0,
    VerdictAction.MASK: 1,
    VerdictAction.BLOCK: 2,
}

_TRANSFORMS = {
    "lower": str.lower,
    "strip": str.strip,
}


@dataclass(frozen=True, slots=True)
class Subject:
    """Text sources available to one checkpoint execution.

    dict 를 넘기지 않는 이유: 요청 경로에서 슬롯 dataclass 가 더 싸고, 필드가 계약이
    되어야 항목을 더할 때 조용히 깨지지 않는다. ``tool_texts`` 의 위치는
    ToolExtract 의 출력 슬롯과 같다. ``None`` 은 선택자에서 제외된 호출이다.
    """

    user_text: str = ""
    tool_result: str = ""
    trusted_text: str = ""
    output_text: str = ""
    tool_texts: tuple[str | None, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """규칙 티어의 답.

    ``pending_model`` 이 §4 의 "모르겠음"이다. 실행기가 이것을 allow 로 바꾸지 않는
    이유: 모델 티어가 없는 지금 여기서 결정해버리면, Phase 4 가 붙을 때 그 결정이
    어디서 났는지 찾을 수 없다. 어떻게 처리할지는 호출자가 한 곳에서 정하고 감사
    로그에 남긴다.
    """

    action: VerdictAction
    checks_fired: tuple[str, ...]
    pending_model: tuple[str, ...]

    @property
    def is_allow(self) -> bool:
        return self.action is VerdictAction.ALLOW


ALLOWED = ExecutionResult(action=VerdictAction.ALLOW, checks_fired=(), pending_model=())


def execute(program: Program, subject: Subject, *, collect_all: bool = False) -> ExecutionResult:
    """Run one checkpoint's program against one subject.

    ``collect_all`` 이 조기 종료를 끈다. enforce 는 어차피 막으므로 첫 BLOCK 에서
    멈추는 것이 맞지만, dry-run 은 튜닝이 존재 이유이므로 걸린 체크가 전부 필요하다
    (§4: "하나만 남기면 정책 튜닝이 불가능해진다").
    """
    if program.is_empty:
        return ALLOWED

    slots: list = [None] * program.slot_count
    action = VerdictAction.ALLOW
    fired: list[str] = []
    pending: list[str] = []

    for instruction in program.instructions:
        match instruction:
            case Extract():
                slots[instruction.out] = getattr(subject, instruction.source)
            case ToolExtract():
                source = (
                    subject.tool_texts[instruction.out]
                    if instruction.out < len(subject.tool_texts)
                    else None
                )
                slots[instruction.out] = SKIPPED if source is None else source
            case Transform():
                source = slots[instruction.src]
                slots[instruction.out] = (
                    source
                    if source is SKIPPED
                    else _TRANSFORMS[instruction.op](source)
                    if source is not None
                    else None
                )
            case ModelCheck():
                slots[instruction.out] = SKIPPED if slots[instruction.src] is SKIPPED else PENDING
            case Not():
                source = slots[instruction.src]
                slots[instruction.out] = (
                    source if source is PENDING or source is SKIPPED else not source
                )
            case RegexOne():
                source = slots[instruction.src]
                slots[instruction.out] = (
                    SKIPPED
                    if source is SKIPPED
                    else instruction.pattern.search(source) is not None
                    if source is not None
                    else False
                )
            case RegexSet():
                _run_regex_set(instruction, slots)
            case Verdict():
                has_pending = False
                if instruction.combine is VerdictCombine.ALL:
                    triggered = True
                    for src in instruction.srcs:
                        value = slots[src]
                        if value is PENDING:
                            triggered = False
                            has_pending = True
                        elif value is not True:
                            triggered = False
                            has_pending = False
                            break
                else:
                    triggered = False
                    for src in instruction.srcs:
                        value = slots[src]
                        if value is True:
                            triggered = True
                            break
                        if value is PENDING:
                            has_pending = True
                if triggered:
                    fired.append(instruction.node_id)
                    if _SEVERITY[instruction.action] > _SEVERITY[action]:
                        action = instruction.action
                    if action is VerdictAction.BLOCK and not collect_all:
                        # §6 의 조기 종료. dry-run 에서는 하지 않는다.
                        break
                elif has_pending:
                    pending.append(instruction.node_id)

    return ExecutionResult(
        action=action,
        checks_fired=tuple(fired),
        pending_model=tuple(pending),
    )


def _run_regex_set(instruction: RegexSet, slots: list) -> None:
    """One pass over the text for every pattern in the group (§11.2).

    ``Match`` 는 매치가 없으면 **None** 을 준다. 빈 리스트로 착각하면 조용히 전부
    통과한다 — 가드레일에서 가장 나쁜 실패 방향이다.
    """
    # 슬롯은 None 으로 시작하고 None 은 falsy 다. 걸리지 않은 패턴을 False 로 덮는
    # 코드를 두면 관측 가능한 차이가 없어서 반증할 수 없는 줄이 된다.
    source = slots[instruction.src]
    if source is SKIPPED:
        for out in instruction.outs:
            slots[out] = SKIPPED
        return
    if source is None:
        return
    hits = instruction.matcher.Match(source)
    if not hits:
        return
    for index in hits:
        slots[instruction.outs[index]] = True
