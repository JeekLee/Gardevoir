"""컴파일러 — 그래프를 직선 명령 목록으로 (§6 의 ②~⑧).

노드 문법 검증은 여기 없다. 저작 시점에 이미 했고, 발행 시점에 다시 하면 컴파일
시간의 절반을 낭비한다 (§11.3).
"""

import pytest

from gateway.application.plan.compiler import compile_guardrail
from gateway.application.plan.execution_plan import (
    Extract,
    Length,
    RegexOne,
    RegexSet,
    Verdict,
)
from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import DRAFT_VERSION, Edge, Guardrail, Node, NodeType
from shared_kernel.exception import ValidationError


def _graph(nodes, edges, *, name: str = "doc-agent", version_number: int = 1) -> Guardrail:
    return Guardrail(
        name=name,
        version=str(version_number),
        version_number=version_number,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def _extract(node_id: str, checkpoint: str = "input") -> Node:
    return Node(id=node_id, type=NodeType.EXTRACT, config={"checkpoint": checkpoint})


def _regex(node_id: str, pattern: str = r"\d{6}") -> Node:
    return Node(id=node_id, type=NodeType.REGEX, config={"pattern": pattern})


def _length(node_id: str, max_chars: int = 100) -> Node:
    return Node(id=node_id, type=NodeType.LENGTH, config={"max_chars": max_chars})


def _transform(node_id: str, op: str = "lower") -> Node:
    return Node(id=node_id, type=NodeType.TRANSFORM, config={"op": op})


def _verdict(node_id: str, decision: str = "conclusive", action: str = "block") -> Node:
    return Node(id=node_id, type=NodeType.VERDICT, config={"decision": decision, "action": action})


def _simple() -> Guardrail:
    """extract -> regex -> verdict"""
    return _graph(
        (_extract("e"), _regex("r"), _verdict("v")),
        (Edge("e", "r"), Edge("r", "v")),
    )


def _kinds(program) -> list[str]:
    return [type(i).__name__ for i in program.instructions]


# --- 기본 -------------------------------------------------------------------


def test_a_single_checkpoint_graph_compiles():
    plan = compile_guardrail(_simple())
    program = plan.program_for("input")
    assert program is not None
    assert _kinds(program) == ["Extract", "RegexOne", "Verdict"]


def test_the_plan_carries_the_guardrail_identity():
    """감사 로그가 이름과 버전을 박는다 (§6)."""
    plan = compile_guardrail(_simple())
    assert plan.guardrail == "doc-agent"
    assert plan.version_number == 1


def test_a_draft_can_be_compiled_for_a_dry_run():
    """발행 전에 dry-run 으로 시험해야 하므로 draft 도 컴파일된다."""
    draft = Guardrail(
        name="doc-agent",
        version=DRAFT_VERSION,
        version_number=None,
        nodes=_simple().nodes,
        edges=_simple().edges,
    )
    plan = compile_guardrail(draft)
    assert plan.version_number == 0, "미발행은 0 으로 기록된다"


def test_each_checkpoint_gets_its_own_program():
    """①은 업스트림 호출 전, ③은 후다. 한 배열로는 실행할 수 없다."""
    plan = compile_guardrail(
        _graph(
            (
                _extract("ei", "input"),
                _regex("ri"),
                _verdict("vi"),
                _extract("eo", "output"),
                _regex("ro"),
                _verdict("vo"),
            ),
            (
                Edge("ei", "ri"),
                Edge("ri", "vi"),
                Edge("eo", "ro"),
                Edge("ro", "vo"),
            ),
        )
    )
    assert plan.checkpoints == frozenset({"input", "output"})
    assert [i.node_id for i in plan.programs["input"].instructions if isinstance(i, Verdict)] == [
        "vi"
    ]
    assert [i.node_id for i in plan.programs["output"].instructions if isinstance(i, Verdict)] == [
        "vo"
    ]


def test_two_extracts_on_one_checkpoint_share_a_program():
    plan = compile_guardrail(
        _graph(
            (_extract("e1"), _extract("e2"), _regex("r1"), _regex("r2"), _verdict("v")),
            (Edge("e1", "r1"), Edge("e2", "r2"), Edge("r1", "v"), Edge("r2", "v")),
        )
    )
    assert plan.checkpoints == frozenset({"input"})


def test_a_verdict_mixing_checkpoints_is_rejected():
    """늦은 쪽에서 평가하려면 이른 쪽 결과를 요청 사이에 들고 있어야 한다 — Phase 3."""
    with pytest.raises(ValidationError) as exc:
        compile_guardrail(
            _graph(
                (
                    _extract("ei", "input"),
                    _extract("eo", "output"),
                    _regex("ri"),
                    _regex("ro"),
                    _verdict("v"),
                ),
                (
                    Edge("ei", "ri"),
                    Edge("eo", "ro"),
                    Edge("ri", "v"),
                    Edge("ro", "v"),
                ),
            )
        )
    assert exc.value.code == GuardrailError.MIXED_CHECKPOINTS.code
    assert exc.value.details["node_id"] == "v"
    assert sorted(exc.value.details["checkpoints"]) == ["input", "output"]


# --- 도달 불가 노드 ----------------------------------------------------------


def test_unreachable_nodes_are_dropped():
    """verdict 에 닿지 않는 분기는 결과에 영향이 없다. UI 에서 흔히 생긴다."""
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _regex("used"), _regex("dangling"), _verdict("v")),
            (Edge("e", "used"), Edge("e", "dangling"), Edge("used", "v")),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    assert len(program.instructions) == 3, _kinds(program)


def test_a_graph_with_no_verdict_compiles_to_nothing():
    """판정이 없으면 실행할 이유가 없다."""
    plan = compile_guardrail(_graph((_extract("e"), _regex("r")), (Edge("e", "r"),)))
    assert plan.checkpoints == frozenset()


def test_an_empty_graph_compiles_to_an_empty_plan():
    plan = compile_guardrail(_graph((), ()))
    assert plan.checkpoints == frozenset()
    assert plan.instruction_count == 0


def test_only_the_checkpoint_with_a_verdict_survives():
    plan = compile_guardrail(
        _graph(
            (_extract("ei", "input"), _regex("ri"), _verdict("v"), _extract("eo", "output")),
            (Edge("ei", "ri"), Edge("ri", "v")),
        )
    )
    assert plan.checkpoints == frozenset({"input"})


# --- 슬롯 -------------------------------------------------------------------


def test_slots_are_dense():
    """slot_count 가 실제로 쓰이는 슬롯 수와 같아야 배열이 낭비되지 않는다."""
    plan = compile_guardrail(_simple())
    program = plan.program_for("input")
    assert program is not None
    used = {i.out for i in program.instructions if hasattr(i, "out")}
    used |= {o for i in program.instructions if isinstance(i, RegexSet) for o in i.outs}
    assert used == set(range(program.slot_count))


def test_slots_are_numbered_per_program():
    """프로그램마다 자기 배열을 쓴다 — 전역 번호면 배열이 필요 없는 만큼 커진다."""
    plan = compile_guardrail(
        _graph(
            (
                _extract("ei", "input"),
                _regex("ri"),
                _verdict("vi"),
                _extract("eo", "output"),
                _regex("ro"),
                _verdict("vo"),
            ),
            (Edge("ei", "ri"), Edge("ri", "vi"), Edge("eo", "ro"), Edge("ro", "vo")),
        )
    )
    for program in plan.programs.values():
        assert program.instructions[0].out == 0


# --- regex 합침 -------------------------------------------------------------


def test_regexes_reading_the_same_slot_are_merged():
    """§11.2: 200 패턴 1패스 0.0086 ms vs 개별 루프. 합치는 것이 요점이다."""
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _regex("r1", "aaa"), _regex("r2", "bbb"), _verdict("v")),
            (Edge("e", "r1"), Edge("e", "r2"), Edge("r1", "v"), Edge("r2", "v")),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    sets = [i for i in program.instructions if isinstance(i, RegexSet)]
    assert len(sets) == 1
    assert len(sets[0].outs) == 2
    assert not [i for i in program.instructions if isinstance(i, RegexOne)]


def test_a_lone_regex_is_not_wrapped_in_a_set():
    program = compile_guardrail(_simple()).program_for("input")
    assert program is not None
    assert [i for i in program.instructions if isinstance(i, RegexOne)]
    assert not [i for i in program.instructions if isinstance(i, RegexSet)]


def test_regexes_reading_different_slots_are_not_merged():
    """서로 다른 텍스트를 보는 패턴을 합치면 결과가 뒤섞인다."""
    plan = compile_guardrail(
        _graph(
            (
                _extract("e"),
                _transform("t"),
                _regex("r_raw", "aaa"),
                _regex("r_lower", "bbb"),
                _verdict("v"),
            ),
            (
                Edge("e", "t"),
                Edge("e", "r_raw"),
                Edge("t", "r_lower"),
                Edge("r_raw", "v"),
                Edge("r_lower", "v"),
            ),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    assert not [i for i in program.instructions if isinstance(i, RegexSet)]
    assert len([i for i in program.instructions if isinstance(i, RegexOne)]) == 2


def test_three_regexes_on_one_slot_become_one_set():
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _regex("a", "aa"), _regex("b", "bb"), _regex("c", "cc"), _verdict("v")),
            (
                Edge("e", "a"),
                Edge("e", "b"),
                Edge("e", "c"),
                Edge("a", "v"),
                Edge("b", "v"),
                Edge("c", "v"),
            ),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    sets = [i for i in program.instructions if isinstance(i, RegexSet)]
    assert len(sets) == 1
    assert len(sets[0].outs) == 3


# --- 순서 -------------------------------------------------------------------


def test_instructions_respect_dependencies():
    """소스가 언제나 먼저다 — 아니면 슬롯이 None 인 상태로 읽힌다."""
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _transform("t"), _regex("r"), _verdict("v")),
            (Edge("e", "t"), Edge("t", "r"), Edge("r", "v")),
        )
    )
    program = plan.program_for("input")
    assert program is not None

    written: set[int] = set()
    for instruction in program.instructions:
        if isinstance(instruction, Verdict):
            assert set(instruction.srcs) <= written
        else:
            if src := getattr(instruction, "src", None):
                assert src in written
            if isinstance(instruction, RegexSet):
                written |= set(instruction.outs)
            else:
                written.add(instruction.out)


def test_cheaper_checks_come_first():
    """조기 종료가 빨라진다. length < transform < regex (§6 의 ⑨)."""
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _regex("r", "aaa"), _length("l"), _verdict("v")),
            (Edge("e", "r"), Edge("e", "l"), Edge("r", "v"), Edge("l", "v")),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    kinds = _kinds(program)
    assert kinds.index("Length") < kinds.index("RegexOne")


def test_reordering_never_breaks_a_dependency():
    """싼 것을 앞으로 당기다가 의존성을 깨면 슬롯이 비어 있는 채로 읽힌다."""
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _transform("t"), _length("l"), _verdict("v")),
            (Edge("e", "t"), Edge("t", "l"), Edge("l", "v")),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    kinds = _kinds(program)
    assert kinds.index("Transform") < kinds.index("Length")


def test_the_verdict_comes_last():
    program = compile_guardrail(_simple()).program_for("input")
    assert program is not None
    assert isinstance(program.instructions[-1], Verdict)


# --- 결정론 -----------------------------------------------------------------


def test_compiling_twice_yields_the_same_shape():
    """워커마다 독립 컴파일한다 (§6). 결과가 흔들리면 판정이 워커마다 달라진다."""
    graph = _graph(
        (_extract("e"), _regex("r1", "aa"), _regex("r2", "bb"), _length("l"), _verdict("v")),
        (
            Edge("e", "r1"),
            Edge("e", "r2"),
            Edge("e", "l"),
            Edge("r1", "v"),
            Edge("r2", "v"),
            Edge("l", "v"),
        ),
    )
    first = compile_guardrail(graph)
    second = compile_guardrail(graph)
    assert _kinds(first.programs["input"]) == _kinds(second.programs["input"])
    assert first.programs["input"].slot_count == second.programs["input"].slot_count


def test_node_config_is_copied_not_referenced():
    """§11.6: 명령이 원본 노드 dict 를 붙들면 파싱된 정의가 통째로 남는다."""
    node = _length("l", 42)
    plan = compile_guardrail(
        _graph((_extract("e"), node, _verdict("v")), (Edge("e", "l"), Edge("l", "v")))
    )
    program = plan.program_for("input")
    assert program is not None
    lengths = [i for i in program.instructions if isinstance(i, Length)]
    assert lengths[0].max_chars == 42

    node.config["max_chars"] = 999
    assert lengths[0].max_chars == 42


def test_transform_chains_compile():
    plan = compile_guardrail(
        _graph(
            (
                _extract("e"),
                _transform("t1", "strip"),
                _transform("t2", "lower"),
                _regex("r"),
                _verdict("v"),
            ),
            (Edge("e", "t1"), Edge("t1", "t2"), Edge("t2", "r"), Edge("r", "v")),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    assert _kinds(program) == ["Extract", "Transform", "Transform", "RegexOne", "Verdict"]


def test_the_extract_checkpoint_is_recorded():
    program = compile_guardrail(_simple()).program_for("input")
    assert program is not None
    assert isinstance(program.instructions[0], Extract)
    assert program.instructions[0].checkpoint == "input"


# --- 워커 간 결정론 -----------------------------------------------------------
#
# §6 은 워커마다 독립 컴파일이라고 한다. 명령 순서가 워커마다 다르면 조기 종료
# 지점이 달라지고, 같은 요청의 checks_fired 가 워커마다 달라져서 감사 로그로
# 정책을 튜닝할 수 없게 된다.
#
# 한 프로세스 안에서 두 번 컴파일하는 것으로는 잡히지 않는다 — 문자열 해시가
# 프로세스마다 다르므로(PYTHONHASHSEED) 하위 프로세스를 띄워서 비교해야 한다.

_SHAPE_PROBE = """
from gateway.application.plan.compiler import compile_guardrail
from gateway.domain.models.guardrail import Edge, Guardrail, Node, NodeType

nodes, edges = [], []
for index in range(6):
    extract, check, verdict = f"e{index}", f"len{index}", f"v{index}"
    nodes.append(Node(id=extract, type=NodeType.EXTRACT, config={"checkpoint": "input"}))
    nodes.append(Node(id=check, type=NodeType.LENGTH, config={"max_chars": 10 + index}))
    nodes.append(Node(id=verdict, type=NodeType.VERDICT,
                      config={"decision": "conclusive", "action": "block"}))
    edges.append(Edge(extract, check))
    edges.append(Edge(check, verdict))

program = compile_guardrail(Guardrail(
    name="probe", version="1", version_number=1, nodes=tuple(nodes), edges=tuple(edges)
)).program_for("input")

shape = []
for i in program.instructions:
    kind = type(i).__name__
    if kind == "Verdict":
        shape.append(f"V{i.srcs[0]}:{i.node_id}")
    elif kind == "Length":
        shape.append(f"L{i.max_chars}->{i.out}")
    else:
        shape.append(f"E{i.out}")
print(",".join(shape))
"""


def _compiled_shape(hash_seed: str) -> str:
    import os
    import subprocess
    import sys

    env = dict(os.environ, PYTHONHASHSEED=hash_seed)
    result = subprocess.run(
        [sys.executable, "-c", _SHAPE_PROBE],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def test_the_instruction_order_does_not_depend_on_the_hash_seed():
    """루트(extract)가 여러 개면 set 순회 순서가 그대로 명령 순서가 된다.

    노드 선언 순서로 정렬을 시작해야 해시와 무관하게 결정적이다.
    """
    shapes = {_compiled_shape(seed) for seed in ("1", "2", "3", "4", "5", "6")}
    assert len(shapes) == 1, f"해시 시드에 따라 순서가 갈렸다: {shapes}"


def test_the_shape_probe_actually_produces_a_shape():
    """위 테스트가 빈 문자열끼리 비교하며 통과하지 않는지 확인한다."""
    shape = _compiled_shape("1")
    assert shape.count("E") == 6
    assert shape.count("L") == 6
    assert shape.count("V") == 6


def test_declaration_order_survives_the_cost_sort():
    """비용이 같으면 선언 순서를 유지해야 한다 — 안정 정렬이어야 결정적이다."""
    plan = compile_guardrail(
        _graph(
            (
                _extract("e"),
                _length("l_third", 30),
                _length("l_first", 10),
                _length("l_second", 20),
                _verdict("v"),
            ),
            (
                Edge("e", "l_third"),
                Edge("e", "l_first"),
                Edge("e", "l_second"),
                Edge("l_third", "v"),
                Edge("l_first", "v"),
                Edge("l_second", "v"),
            ),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    lengths = [i.max_chars for i in program.instructions if isinstance(i, Length)]
    assert lengths == [30, 10, 20], "선언 순서가 아니라 다른 것으로 정렬됐다"


def test_roots_are_emitted_in_declaration_order():
    """루트(extract)가 여러 개면 그 순서가 슬롯 번호와 명령 순서를 정한다.

    해시 시드 테스트는 '일관성'만 본다 — 순서를 뒤집어도 일관되므로 통과한다.
    저작자가 읽을 수 있는 순서(선언 순서)인지는 따로 고정해야 한다.
    """
    plan = compile_guardrail(
        _graph(
            (
                _extract("e_third"),
                _extract("e_first"),
                _extract("e_second"),
                _length("l_third", 30),
                _length("l_first", 10),
                _length("l_second", 20),
                _verdict("v"),
            ),
            (
                Edge("e_third", "l_third"),
                Edge("e_first", "l_first"),
                Edge("e_second", "l_second"),
                Edge("l_third", "v"),
                Edge("l_first", "v"),
                Edge("l_second", "v"),
            ),
        )
    )
    program = plan.program_for("input")
    assert program is not None

    extracts = [i for i in program.instructions if isinstance(i, Extract)]
    assert [i.out for i in extracts] == [0, 1, 2]

    # e_third 가 먼저 선언됐으므로 슬롯 0 이고, 그것을 읽는 length 가 max_chars=30 이다
    lengths = [i for i in program.instructions if isinstance(i, Length)]
    by_source = {i.src: i.max_chars for i in lengths}
    assert by_source == {0: 30, 1: 10, 2: 20}


# --- MASK 는 위치가 필요하다 --------------------------------------------------
#
# 실행기는 "걸렸다/안 걸렸다"만 안다. 마스킹은 위치가 필요해서 걸린 패턴을 원본에
# 다시 돌려야 하는데, 그 패턴이 transform 출력(소문자화 등)을 읽었으면 원본에서는
# 안 걸릴 수 있다. 그러면 action=mask 라고 응답하면서 아무것도 가리지 않는다 —
# 조용한 fail-open 이다. 런타임에 그 상황이 오지 않게 컴파일 시점에 거부한다.


def _mask(node_id: str = "v") -> Node:
    return _verdict(node_id, action="mask")


def test_a_mask_verdict_on_a_direct_regex_compiles():
    plan = compile_guardrail(
        _graph((_extract("e"), _regex("r"), _mask()), (Edge("e", "r"), Edge("r", "v")))
    )
    assert plan.program_for("input") is not None


def test_a_mask_verdict_behind_a_transform_is_rejected():
    with pytest.raises(ValidationError) as exc:
        compile_guardrail(
            _graph(
                (_extract("e"), _transform("t"), _regex("r"), _mask()),
                (Edge("e", "t"), Edge("t", "r"), Edge("r", "v")),
            )
        )
    assert exc.value.code == GuardrailError.UNMASKABLE.code
    assert exc.value.details["node_id"] == "v"


def test_a_mask_verdict_on_a_length_check_is_rejected():
    """length 는 위치가 없다 — 무엇을 가릴지 정할 수 없다."""
    with pytest.raises(ValidationError) as exc:
        compile_guardrail(
            _graph((_extract("e"), _length("l"), _mask()), (Edge("e", "l"), Edge("l", "v")))
        )
    assert exc.value.code == GuardrailError.UNMASKABLE.code


def test_a_mask_verdict_with_one_bad_input_is_rejected():
    """입력이 여러 개면 OR 다 — 하나만 위치를 모르면 그 하나로 fail-open 이 된다."""
    with pytest.raises(ValidationError) as exc:
        compile_guardrail(
            _graph(
                (_extract("e"), _regex("ok"), _length("bad"), _mask()),
                (Edge("e", "ok"), Edge("e", "bad"), Edge("ok", "v"), Edge("bad", "v")),
            )
        )
    assert exc.value.code == GuardrailError.UNMASKABLE.code


def test_a_block_verdict_behind_a_transform_still_compiles():
    """제한은 MASK 만이다. 차단은 위치가 필요 없다."""
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _transform("t"), _regex("r"), _verdict("v")),
            (Edge("e", "t"), Edge("t", "r"), Edge("r", "v")),
        )
    )
    assert plan.program_for("input") is not None


def test_a_block_verdict_on_a_length_check_still_compiles():
    plan = compile_guardrail(
        _graph((_extract("e"), _length("l"), _verdict("v")), (Edge("e", "l"), Edge("l", "v")))
    )
    assert plan.program_for("input") is not None


def test_an_allow_verdict_is_not_restricted():
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _length("l"), _verdict("v", action="allow")),
            (Edge("e", "l"), Edge("l", "v")),
        )
    )
    assert plan.program_for("input") is not None


# --- 마스킹용 패턴 -----------------------------------------------------------


def test_patterns_by_slot_covers_every_regex_slot():
    """마스킹은 걸린 슬롯에서 패턴을 되찾아야 한다."""
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _regex("r1", "aa"), _regex("r2", "bb"), _mask()),
            (Edge("e", "r1"), Edge("e", "r2"), Edge("r1", "v"), Edge("r2", "v")),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    regex_slots = {o for i in program.instructions if isinstance(i, RegexSet) for o in i.outs}
    regex_slots |= {i.out for i in program.instructions if isinstance(i, RegexOne)}
    assert set(program.patterns_by_slot) == regex_slots


def test_patterns_by_slot_is_empty_without_regexes():
    plan = compile_guardrail(
        _graph((_extract("e"), _length("l"), _verdict("v")), (Edge("e", "l"), Edge("l", "v")))
    )
    program = plan.program_for("input")
    assert program is not None
    assert program.patterns_by_slot == {}


def test_patterns_by_slot_finds_the_right_pattern():
    plan = compile_guardrail(
        _graph(
            (_extract("e"), _regex("r1", "alpha"), _regex("r2", "bravo"), _mask()),
            (Edge("e", "r1"), Edge("e", "r2"), Edge("r1", "v"), Edge("r2", "v")),
        )
    )
    program = plan.program_for("input")
    assert program is not None
    matched = {
        slot for slot, pattern in program.patterns_by_slot.items() if pattern.search("alpha")
    }
    assert len(matched) == 1
