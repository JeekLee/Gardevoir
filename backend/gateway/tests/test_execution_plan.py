"""컴파일 산출물의 성질.

이 타입들은 요청 경로에 있다 — 불변성과 슬롯은 성능 계약이다 (§11.6, §11.8).
"""

import dataclasses

import pytest

from gateway.application.plan.execution_plan import (
    ExecutionPlan,
    Extract,
    Length,
    Program,
    RegexOne,
    RegexSet,
    Transform,
    Verdict,
)
from gateway.domain.models.guardrail import Decision, VerdictAction

INSTRUCTIONS = [
    Extract(out=0, checkpoint="input"),
    Transform(out=1, src=0, op="lower"),
    Length(out=2, src=1, max_chars=10),
    RegexOne(out=3, src=1, pattern=object()),
    RegexSet(outs=(4, 5), src=1, matcher=object()),
    Verdict(srcs=(2,), decision=Decision.CONCLUSIVE, action=VerdictAction.BLOCK, node_id="v"),
]


def _plan(**programs: Program) -> ExecutionPlan:
    return ExecutionPlan(guardrail="doc-agent", version_number=3, programs=dict(programs))


def _program(*instructions) -> Program:
    return Program(instructions=tuple(instructions), slot_count=len(instructions))


# --- 계획 -------------------------------------------------------------------


def test_program_for_returns_none_for_an_unused_checkpoint():
    """2c 가 이걸 보고 체크포인트를 통째로 건너뛴다."""
    plan = _plan(input=_program(Extract(out=0, checkpoint="input")))
    assert plan.program_for("input") is not None
    assert plan.program_for("output") is None


def test_checkpoints_lists_only_what_the_plan_inspects():
    plan = _plan(input=_program(Extract(out=0, checkpoint="input")))
    assert plan.checkpoints == frozenset({"input"})


def test_a_plan_with_no_programs_inspects_nothing():
    assert _plan().checkpoints == frozenset()
    assert _plan().program_for("input") is None


def test_instruction_count_spans_every_program():
    plan = _plan(
        input=_program(Extract(out=0, checkpoint="input")),
        output=_program(Extract(out=0, checkpoint="output"), Length(out=1, src=0, max_chars=5)),
    )
    assert plan.instruction_count == 3


def test_the_plan_records_the_version_number():
    """감사 로그가 이 번호를 박는다 — 없으면 몇 달 뒤 '왜 막혔지'를 답할 수 없다 (§6)."""
    assert _plan().version_number == 3


def test_an_empty_program_reports_itself_empty():
    assert Program(instructions=(), slot_count=0).is_empty is True
    assert _program(Extract(out=0, checkpoint="input")).is_empty is False


# --- 불변성 / 메모리 ---------------------------------------------------------


@pytest.mark.parametrize("instruction", INSTRUCTIONS, ids=lambda i: type(i).__name__)
def test_instructions_are_immutable(instruction):
    """계획은 여러 요청이 동시에 읽는다. 실행이 명령을 고치면 서로 오염된다."""
    # 명령마다 필드가 다르므로 첫 슬롯에 쓴다. 없는 이름에 쓰면 frozen 이 아니라
    # 속성 부재로 터져서 아무것도 검증하지 못한다.
    existing = instruction.__slots__[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instruction, existing, 99)


@pytest.mark.parametrize("instruction", INSTRUCTIONS, ids=lambda i: type(i).__name__)
def test_instructions_have_slots(instruction):
    """__dict__ 가 붙으면 계획 하나가 명령당 수백 바이트씩 커진다 (§11.6)."""
    assert not hasattr(instruction, "__dict__")


@pytest.mark.parametrize("instruction", INSTRUCTIONS, ids=lambda i: type(i).__name__)
def test_an_instruction_does_not_hold_a_node_dict(instruction):
    """§11.6 의 307 KB 는 명령이 원본 노드 dict 를 참조로 붙들어서 나온 값이다."""
    values = [getattr(instruction, name) for name in instruction.__slots__]
    assert not [v for v in values if isinstance(v, dict)]


def test_the_plan_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _plan().version_number = 4  # type: ignore[misc]


def test_a_program_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _program().slot_count = 9  # type: ignore[misc]


def test_verdict_carries_the_node_id():
    """checks_fired 가 정책 튜닝의 유일한 입력이다 (§4)."""
    verdict = INSTRUCTIONS[-1]
    assert verdict.node_id == "v"


def test_verdict_has_no_output_slot():
    """판정은 슬롯에 쓰지 않는다 — bool 이 아니라 action 과 node_id 가 필요하다."""
    assert "out" not in Verdict.__slots__
