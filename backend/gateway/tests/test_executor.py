"""실행기 — 컴파일된 프로그램을 텍스트에 적용한다.

컴파일러를 거쳐 만든 계획으로 테스트한다. 명령을 손으로 조립하면 컴파일러와 실행기가
서로 어긋나도 둘 다 초록색이 된다.
"""

import pytest

from gateway.application.plan.compiler import compile_guardrail
from gateway.application.plan.executor import Subject, execute
from gateway.domain.models.guardrail import Edge, Guardrail, Node, NodeType, VerdictAction


def _node(node_id: str, node_type: NodeType, **config) -> Node:
    return Node(id=node_id, type=node_type, config=config)


def _program(nodes, edges, checkpoint: str = "input"):  # noqa: D401
    guardrail = Guardrail(
        name="doc-agent",
        version="1",
        version_number=1,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )
    guardrail.validate()
    program = compile_guardrail(guardrail).program_for(checkpoint)
    assert program is not None, "컴파일이 이 체크포인트의 프로그램을 내지 않았다"
    return program


def _run(program, text: str, **kw):
    """텍스트만 있는 검사 — Subject 의 나머지 필드는 기본값(안전한 쪽)이다."""
    return execute(program, Subject(text=text), **kw)


def _regex_block(pattern: str = r"\d{6}-\d{7}", action: str = "block"):
    return _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("r", NodeType.REGEX, pattern=pattern),
            _node("v", NodeType.VERDICT, decision="conclusive", action=action),
        ),
        (Edge("e", "r"), Edge("r", "v")),
    )


# --- 기본 -------------------------------------------------------------------


def test_a_clean_text_is_allowed():
    result = _run(_regex_block(), "hello there")
    assert result.action is VerdictAction.ALLOW
    assert result.checks_fired == ()
    assert result.is_allow is True


def test_a_matching_regex_blocks():
    result = _run(_regex_block(), "my id is 900101-1234567")
    assert result.action is VerdictAction.BLOCK
    assert result.is_allow is False


def test_the_fired_node_is_reported():
    """checks_fired 가 정책 튜닝의 유일한 입력이다 (§4)."""
    result = _run(_regex_block(), "900101-1234567")
    assert result.checks_fired == ("v",)


def test_an_empty_program_allows():
    from gateway.application.plan.execution_plan import Program

    assert _run(Program(instructions=(), slot_count=0), "anything").is_allow


# --- regex set ---------------------------------------------------------------


def _two_patterns(action_a: str = "block", action_b: str = "block"):
    return _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("ra", NodeType.REGEX, pattern="alpha"),
            _node("rb", NodeType.REGEX, pattern="bravo"),
            _node("va", NodeType.VERDICT, decision="conclusive", action=action_a),
            _node("vb", NodeType.VERDICT, decision="conclusive", action=action_b),
        ),
        (Edge("e", "ra"), Edge("e", "rb"), Edge("ra", "va"), Edge("rb", "vb")),
    )


def test_a_regex_set_fires_only_the_matching_member():
    """합친 Set 의 인덱스가 슬롯에 잘못 매핑되면 엉뚱한 판정이 선다."""
    result = _run(_two_patterns(), "only alpha here", collect_all=True)
    assert result.checks_fired == ("va",)


def test_a_regex_set_fires_the_other_member():
    result = _run(_two_patterns(), "only bravo here", collect_all=True)
    assert result.checks_fired == ("vb",)


def test_a_regex_set_can_fire_both():
    result = _run(_two_patterns(), "alpha and bravo", collect_all=True)
    assert sorted(result.checks_fired) == ["va", "vb"]


def test_a_regex_set_fires_nothing_on_a_clean_text():
    """re2 Set.Match 는 매치가 없으면 None 을 준다. 빈 리스트로 보면 전부 통과한다."""
    result = _run(_two_patterns(), "nothing relevant", collect_all=True)
    assert result.checks_fired == ()
    assert result.is_allow


# --- length -----------------------------------------------------------------


def _length_block(max_chars: int = 10):
    return _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("l", NodeType.LENGTH, max_chars=max_chars),
            _node("v", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (Edge("e", "l"), Edge("l", "v")),
    )


def test_length_fires_over_the_limit():
    assert _run(_length_block(10), "x" * 11).action is VerdictAction.BLOCK


def test_length_does_not_fire_at_the_limit():
    """경계. max_chars 는 허용 최대값이다."""
    assert _run(_length_block(10), "x" * 10).is_allow


def test_length_does_not_fire_under_the_limit():
    assert _run(_length_block(10), "x" * 9).is_allow


# --- transform --------------------------------------------------------------


def test_transform_feeds_the_next_check():
    program = _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("t", NodeType.TRANSFORM, op="lower"),
            _node("r", NodeType.REGEX, pattern="secret"),
            _node("v", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (Edge("e", "t"), Edge("t", "r"), Edge("r", "v")),
    )
    assert _run(program, "SECRET").action is VerdictAction.BLOCK


def test_the_raw_text_is_not_transformed_for_other_branches():
    """transform 은 자기 슬롯만 바꾼다 — 원본을 읽는 분기가 오염되면 안 된다."""
    program = _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("t", NodeType.TRANSFORM, op="lower"),
            _node("r_lower", NodeType.REGEX, pattern="secret"),
            _node("r_raw", NodeType.REGEX, pattern="SECRET"),
            _node("v", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (
            Edge("e", "t"),
            Edge("t", "r_lower"),
            Edge("e", "r_raw"),
            Edge("r_raw", "v"),
        ),
    )
    assert _run(program, "SECRET").action is VerdictAction.BLOCK


def test_strip_transforms():
    program = _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("t", NodeType.TRANSFORM, op="strip"),
            _node("l", NodeType.LENGTH, max_chars=3),
            _node("v", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (Edge("e", "t"), Edge("t", "l"), Edge("l", "v")),
    )
    assert _run(program, "   abc   ").is_allow, "공백을 떼면 3자다"


# --- 판정 우선순위 -----------------------------------------------------------


def test_block_beats_mask():
    """강한 판정이 이긴다 (§4)."""
    result = _run(_two_patterns("mask", "block"), "alpha and bravo", collect_all=True)
    assert result.action is VerdictAction.BLOCK


def test_block_beats_mask_regardless_of_order():
    result = _run(_two_patterns("block", "mask"), "alpha and bravo", collect_all=True)
    assert result.action is VerdictAction.BLOCK


def test_mask_beats_allow():
    result = _run(_two_patterns("mask", "allow"), "alpha and bravo", collect_all=True)
    assert result.action is VerdictAction.MASK


def test_an_explicit_allow_does_not_override_a_block():
    result = _run(_two_patterns("allow", "block"), "alpha and bravo", collect_all=True)
    assert result.action is VerdictAction.BLOCK


# --- 2티어: 모르겠음 ---------------------------------------------------------


def test_a_hint_does_not_decide():
    """규칙에 걸리면 모델로 넘긴다 — 규칙 스스로 판정하지 않는다 (§4)."""
    program = _regex_block()
    hinting = _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("r", NodeType.REGEX, pattern=r"\d{6}-\d{7}"),
            _node("v", NodeType.VERDICT, decision="hint", action="block"),
        ),
        (Edge("e", "r"), Edge("r", "v")),
    )
    assert _run(program, "900101-1234567").action is VerdictAction.BLOCK

    result = _run(hinting, "900101-1234567")
    assert result.action is VerdictAction.ALLOW, "모델 없이 규칙이 막아서는 안 된다"
    assert result.pending_model == ("v",)
    assert result.checks_fired == ("v",)


def test_a_model_only_verdict_pends_when_its_input_fires():
    program = _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("l", NodeType.LENGTH, max_chars=1),
            _node("v", NodeType.VERDICT, decision="model_only", action="block"),
        ),
        (Edge("e", "l"), Edge("l", "v")),
    )
    result = _run(program, "long enough")
    assert result.pending_model == ("v",)
    assert result.action is VerdictAction.ALLOW


def test_a_hint_that_does_not_fire_pends_nothing():
    hinting = _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("r", NodeType.REGEX, pattern=r"\d{6}-\d{7}"),
            _node("v", NodeType.VERDICT, decision="hint", action="block"),
        ),
        (Edge("e", "r"), Edge("r", "v")),
    )
    result = _run(hinting, "nothing here")
    assert result.pending_model == ()
    assert result.checks_fired == ()


# --- 조기 종료 / dry-run ----------------------------------------------------


def _two_blocks():
    """두 판정이 각각 다른 검사에 달려 있고, 둘 다 걸리는 텍스트를 쓴다."""
    return _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("l", NodeType.LENGTH, max_chars=1),
            _node("r", NodeType.REGEX, pattern="alpha"),
            _node("v_cheap", NodeType.VERDICT, decision="conclusive", action="block"),
            _node("v_later", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (Edge("e", "l"), Edge("e", "r"), Edge("l", "v_cheap"), Edge("r", "v_later")),
    )


def test_enforce_stops_at_the_first_block():
    """§6 의 조기 종료. 싼 검사가 앞에 오도록 컴파일되므로 length 가 먼저 선다."""
    result = _run(_two_blocks(), "alpha text")
    assert result.action is VerdictAction.BLOCK
    assert result.checks_fired == ("v_cheap",)


def test_dry_run_collects_every_check():
    """튜닝이 존재 이유다 — 하나만 남기면 오탐을 찾을 수 없다 (§4)."""
    result = _run(_two_blocks(), "alpha text", collect_all=True)
    assert result.action is VerdictAction.BLOCK
    assert sorted(result.checks_fired) == ["v_cheap", "v_later"]


def test_dry_run_and_enforce_agree_on_the_action():
    enforce = _run(_two_blocks(), "alpha text")
    dry_run = _run(_two_blocks(), "alpha text", collect_all=True)
    assert enforce.action is dry_run.action


def test_a_mask_does_not_stop_execution():
    """조기 종료는 BLOCK 에서만 한다 — mask 뒤에 오는 판정이 그것을 뒤집을 수 있다.

    두 검사를 같은 비용(regex)으로 두어야 선언 순서가 판정 순서가 된다 — 비용이
    다르면 싼 쪽 검사가 먼저 끝나서 그쪽 판정이 앞선다.
    mask 판정은 extract 를 직접 읽는 regex 에만 걸 수 있다 (GUARDRAIL-014).
    """
    program = _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("r_mask", NodeType.REGEX, pattern="alpha"),
            _node("r_block", NodeType.REGEX, pattern="bravo"),
            _node("v_mask", NodeType.VERDICT, decision="conclusive", action="mask"),
            _node("v_block", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (
            Edge("e", "r_mask"),
            Edge("e", "r_block"),
            Edge("r_mask", "v_mask"),
            Edge("r_block", "v_block"),
        ),
    )
    result = _run(program, "alpha bravo")
    assert result.checks_fired == ("v_mask", "v_block"), "mask 가 실행을 멈췄다"
    assert result.action is VerdictAction.BLOCK


# --- OR / 재사용 -------------------------------------------------------------


def test_a_verdict_with_many_inputs_is_an_or():
    program = _program(
        (
            _node("e", NodeType.EXTRACT, checkpoint="input"),
            _node("ra", NodeType.REGEX, pattern="alpha"),
            _node("rb", NodeType.REGEX, pattern="bravo"),
            _node("v", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (Edge("e", "ra"), Edge("e", "rb"), Edge("ra", "v"), Edge("rb", "v")),
    )
    assert _run(program, "alpha").action is VerdictAction.BLOCK
    assert _run(program, "bravo").action is VerdictAction.BLOCK
    assert _run(program, "charlie").is_allow


@pytest.mark.parametrize("text", ["900101-1234567", "clean", "900101-1234567"])
def test_running_a_program_repeatedly_is_stable(text):
    """계획은 재사용된다. 실행이 상태를 남기면 두 번째 요청의 판정이 달라진다."""
    program = _regex_block()
    first = _run(program, text)
    second = _run(program, text)
    assert first == second


def test_slots_do_not_leak_between_runs():
    program = _regex_block()
    assert _run(program, "900101-1234567").action is VerdictAction.BLOCK
    assert _run(program, "clean").is_allow, "이전 실행의 슬롯이 남았다"


def test_execution_does_not_mutate_the_program():
    program = _regex_block()
    before = program.instructions
    _run(program, "900101-1234567")
    assert program.instructions is before


# --- 오염 (§8 1단계) --------------------------------------------------------


def _taint_block(checkpoint: str = "tool_call"):
    """taint -> verdict. extract 가 없어도 되는 그래프."""
    return _program(
        (
            _node("t", NodeType.TAINT, checkpoint=checkpoint),
            _node("v", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (Edge("t", "v"),),
        checkpoint,
    )


def test_taint_blocks_a_tainted_conversation():
    result = execute(_taint_block(), Subject(tainted=True))
    assert result.action is VerdictAction.BLOCK
    assert result.checks_fired == ("v",)


def test_taint_allows_a_clean_conversation():
    assert execute(_taint_block(), Subject(tainted=False)).is_allow


def test_a_subject_defaults_to_clean():
    """기본값은 안전한 쪽이 아니라 '오염 아님'이다 — 오염을 근거로 막기 때문이다.

    기본을 True 로 두면 오염 여부를 계산하지 않은 경로가 전부 차단된다.
    """
    assert Subject().tainted is False
    assert Subject().text == ""
    assert execute(_taint_block(), Subject()).is_allow


def test_taint_needs_no_text():
    """오염은 문자열이 아니라 구조적 사실이다 (§8)."""
    assert execute(_taint_block(), Subject(tainted=True)).action is VerdictAction.BLOCK


# --- ALL (§8 2단계의 AND) ---------------------------------------------------


def _taint_and_regex(pattern: str = "alpha", action: str = "block"):
    """오염됨 AND 패턴 일치 — §8 2단계의 모양."""
    return _program(
        (
            _node("t", NodeType.TAINT, checkpoint="tool_call"),
            _node("e", NodeType.EXTRACT, checkpoint="tool_call"),
            _node("r", NodeType.REGEX, pattern=pattern),
            _node("a", NodeType.ALL),
            _node("v", NodeType.VERDICT, decision="conclusive", action=action),
        ),
        (Edge("e", "r"), Edge("t", "a"), Edge("r", "a"), Edge("a", "v")),
        "tool_call",
    )


@pytest.mark.parametrize(
    ("tainted", "text", "blocked"),
    [
        (True, "alpha", True),
        (True, "clean", False),
        (False, "alpha", False),
        (False, "clean", False),
    ],
)
def test_all_is_true_only_when_every_input_is(tainted, text, blocked):
    result = execute(_taint_and_regex(), Subject(text=text, tainted=tainted))
    assert (result.action is VerdictAction.BLOCK) is blocked


def test_all_with_three_inputs():
    program = _program(
        (
            _node("t", NodeType.TAINT, checkpoint="tool_call"),
            _node("e", NodeType.EXTRACT, checkpoint="tool_call"),
            _node("r1", NodeType.REGEX, pattern="alpha"),
            _node("r2", NodeType.REGEX, pattern="bravo"),
            _node("a", NodeType.ALL),
            _node("v", NodeType.VERDICT, decision="conclusive", action="block"),
        ),
        (
            Edge("e", "r1"),
            Edge("e", "r2"),
            Edge("t", "a"),
            Edge("r1", "a"),
            Edge("r2", "a"),
            Edge("a", "v"),
        ),
        "tool_call",
    )
    assert execute(program, Subject(text="alpha bravo", tainted=True)).action is VerdictAction.BLOCK
    assert execute(program, Subject(text="alpha only", tainted=True)).is_allow


def test_all_output_can_feed_two_verdicts():
    """ALL 을 노드로 둔 이유 — 출력을 여러 판정이 재사용한다."""
    program = _program(
        (
            _node("t", NodeType.TAINT, checkpoint="tool_call"),
            _node("e", NodeType.EXTRACT, checkpoint="tool_call"),
            _node("r", NodeType.REGEX, pattern="alpha"),
            _node("a", NodeType.ALL),
            _node("v1", NodeType.VERDICT, decision="conclusive", action="block"),
            _node("v2", NodeType.VERDICT, decision="hint", action="block"),
        ),
        (
            Edge("e", "r"),
            Edge("t", "a"),
            Edge("r", "a"),
            Edge("a", "v1"),
            Edge("a", "v2"),
        ),
        "tool_call",
    )
    result = execute(program, Subject(text="alpha", tainted=True), collect_all=True)
    assert sorted(result.checks_fired) == ["v1", "v2"]
    assert result.pending_model == ("v2",)
