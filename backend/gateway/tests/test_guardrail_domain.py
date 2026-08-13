import dataclasses

import pytest

from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import (
    DRAFT_VERSION,
    Decision,
    Edge,
    Guardrail,
    Node,
    NodeType,
    VerdictAction,
)
from shared_kernel.exception import ConflictError, ValidationError
from tests.layering import imports_of


def _extract(node_id: str = "n0", checkpoint: str = "input") -> Node:
    return Node(id=node_id, type=NodeType.EXTRACT, config={"checkpoint": checkpoint})


def _regex(node_id: str = "n1", pattern: str = r"\d{6}-\d{7}") -> Node:
    return Node(id=node_id, type=NodeType.REGEX, config={"pattern": pattern})


def _verdict(node_id: str = "n2") -> Node:
    return Node(
        id=node_id,
        type=NodeType.VERDICT,
        config={"decision": Decision.CONCLUSIVE, "action": VerdictAction.BLOCK},
    )


def _draft(nodes=None, edges=None, name: str = "doc-agent") -> Guardrail:
    if nodes is None:
        nodes = (_extract(), _regex(), _verdict())
    if edges is None:
        edges = (Edge("n0", "n1"), Edge("n1", "n2"))
    return Guardrail(
        name=name,
        version=DRAFT_VERSION,
        version_number=None,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


# --- 그래프 검증 -------------------------------------------------------------


def test_valid_graph_passes():
    _draft().validate()  # 예외가 나면 실패


def test_empty_graph_is_valid():
    """노드 0개는 아무것도 하지 않는 가드레일이다 — 유효하다."""
    _draft(nodes=(), edges=()).validate()


def test_cycle_is_rejected():
    graph = _draft(edges=(Edge("n0", "n1"), Edge("n1", "n2"), Edge("n2", "n0")))
    with pytest.raises(ValidationError) as info:
        graph.validate()
    assert info.value.code == "GUARDRAIL-002"
    assert set(info.value.details["nodes"]) == {"n0", "n1", "n2"}


def test_self_loop_is_rejected():
    with pytest.raises(ValidationError) as info:
        _draft(edges=(Edge("n1", "n1"),)).validate()
    assert info.value.code == "GUARDRAIL-002"


def test_dangling_edge_is_rejected():
    with pytest.raises(ValidationError) as info:
        _draft(edges=(Edge("n0", "nowhere"),)).validate()
    assert info.value.code == "GUARDRAIL-003"
    assert info.value.details["missing"] == ["nowhere"]


def test_duplicate_node_id_is_rejected():
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_extract("dup"), _regex("dup")), edges=()).validate()
    assert info.value.code == "GUARDRAIL-004"
    assert info.value.details["node_id"] == "dup"


# --- 노드 설정 검증 ----------------------------------------------------------


def test_regex_pattern_is_validated_with_re2():
    """re2 는 (a+)+$ 를 안전하게 다루므로 거부하지 않는다 (§11.1)."""
    _draft(
        nodes=(_extract("n0"), _regex("n1", r"(a+)+$"), _verdict("n2")),
        edges=(Edge("n0", "n1"), Edge("n1", "n2")),
    ).validate()


def test_uncompilable_regex_is_rejected():
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_regex("bad", "[unclosed"),), edges=()).validate()
    assert info.value.code == "GUARDRAIL-005"
    assert info.value.details["node_id"] == "bad"


def test_the_regex_reason_is_text_not_a_bytes_repr():
    """re2 는 이유를 bytes 로 올린다. b'...' 가 응답에 실리면 저작자가 읽을 수 없다."""
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_regex("bad", "[unclosed"),), edges=()).validate()
    reason = info.value.details["reason"]
    assert "b'" not in reason
    assert "missing ]" in reason


def test_regex_requires_a_non_empty_pattern():
    with pytest.raises(ValidationError):
        _draft(nodes=(_regex("bad", ""),), edges=()).validate()


def test_extract_requires_a_known_checkpoint():
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_extract("bad", "nowhere"),), edges=()).validate()
    assert info.value.code == "GUARDRAIL-005"
    assert info.value.details["node_id"] == "bad"


def test_length_requires_a_positive_max():
    for bad_value in (0, -1, "10", True, None):
        node = Node(id="bad", type=NodeType.LENGTH, config={"max_chars": bad_value})
        with pytest.raises(ValidationError):
            _draft(nodes=(node,), edges=()).validate()


def test_length_accepts_a_positive_int():
    node = Node(id="ok", type=NodeType.LENGTH, config={"max_chars": 4000})
    _draft(
        nodes=(_extract("n0"), node, _verdict("n2")),
        edges=(Edge("n0", "ok"), Edge("ok", "n2")),
    ).validate()


def test_transform_requires_a_known_op():
    with pytest.raises(ValidationError):
        _draft(
            nodes=(Node(id="bad", type=NodeType.TRANSFORM, config={"op": "reverse"}),), edges=()
        ).validate()


def test_verdict_requires_known_decision_and_action():
    bad_decision = Node(
        id="bad", type=NodeType.VERDICT, config={"decision": "definite", "action": "block"}
    )
    bad_action = Node(
        id="bad", type=NodeType.VERDICT, config={"decision": "conclusive", "action": "reject"}
    )
    for node in (bad_decision, bad_action):
        with pytest.raises(ValidationError):
            _draft(nodes=(node,), edges=()).validate()


def test_unknown_node_type_is_rejected():
    node = Node(id="weird", type="teleport", config={})  # type: ignore[arg-type]
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(node,), edges=()).validate()
    assert info.value.code == "GUARDRAIL-005"


def test_validate_reports_the_offending_node():
    """UI 가 어느 노드를 붉게 칠할지 알아야 한다."""
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_extract("first"), _regex("broken", "[")), edges=()).validate()
    assert info.value.details["node_id"] == "broken"


# --- 버전 -------------------------------------------------------------------


def test_is_draft():
    assert _draft().is_draft is True
    assert _draft().published_as(3).is_draft is False


def test_guardrail_is_immutable():
    graph = _draft()
    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.name = "other"  # type: ignore[misc]


def test_published_as_produces_an_immutable_copy():
    draft = _draft()
    published = draft.published_as(3)

    assert published.version == "3"
    assert published.version_number == 3
    assert published.nodes == draft.nodes
    # 원본은 draft 로 남는다 — 발행 후에도 계속 편집할 수 있어야 한다
    assert draft.version == DRAFT_VERSION
    assert draft.version_number is None


def test_published_guardrail_cannot_be_published_again():
    with pytest.raises(ConflictError) as info:
        _draft().published_as(1).published_as(2)
    assert info.value.code == "GUARDRAIL-007"


def test_error_codes_are_stable():
    """감사 로그와 클라이언트 처리에 쓰이므로 코드는 계약이다."""
    assert GuardrailError.NOT_FOUND.code == "GUARDRAIL-001"
    assert GuardrailError.CYCLE.code == "GUARDRAIL-002"
    assert GuardrailError.DANGLING_EDGE.code == "GUARDRAIL-003"
    assert GuardrailError.DUPLICATE_NODE_ID.code == "GUARDRAIL-004"
    assert GuardrailError.INVALID_NODE_CONFIG.code == "GUARDRAIL-005"
    assert GuardrailError.NAME_TAKEN.code == "GUARDRAIL-006"
    assert GuardrailError.PUBLISHED_IS_IMMUTABLE.code == "GUARDRAIL-007"
    assert GuardrailError.NO_DRAFT.code == "GUARDRAIL-008"
    assert GuardrailError.MALFORMED_GRAPH.code == "GUARDRAIL-009"
    assert GuardrailError.INVALID_NAME.code == "GUARDRAIL-010"


def test_domain_imports_nothing_from_outer_layers():
    """domain 은 순수해야 한다 (skills/gardevoir-be)."""
    import pathlib

    import gateway.domain.models.guardrail as mod

    names = imports_of(pathlib.Path(mod.__file__))
    forbidden = {"sqlalchemy", "fastapi", "httpx", "clickhouse_connect", "starlette"}
    assert not {n.split(".")[0] for n in names} & forbidden
    assert not [
        n
        for n in names
        if n.startswith(("gateway.application", "gateway.infrastructure", "gateway.presentation"))
    ]


# --- 이름 -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a", "doc-agent", "pii-v2", "a1-b2-c3", "x" * 64])
def test_valid_names_are_accepted(name):
    _draft(name=name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-leading",
        "trailing-",
        "Doc-Agent",
        "doc agent",
        "doc/agent",
        "doc.agent",
        "doc_agent",
        "x" * 65,
        "가드레일",
    ],
)
def test_invalid_names_are_rejected(name):
    """이름은 URL 경로 조각이자 헤더 값이고 allowed_guardrails 와 비교된다."""
    with pytest.raises(ValidationError) as info:
        _draft(name=name)
    assert info.value.code == "GUARDRAIL-010"


def test_a_rejected_name_names_itself():
    with pytest.raises(ValidationError) as info:
        _draft(name="Bad Name")
    assert info.value.details == {"name": "Bad Name"}


# --- 입력 개수(arity) -------------------------------------------------------
#
# 컴파일러가 "regex 는 읽을 슬롯이 정확히 하나"를 가정할 수 있어야 한다.
# 도메인에 두는 이유: 컴파일 시점에 처음 터지면 발행이 문법 오류로 실패하는데,
# §6 이 문법 검증을 저작 시점으로 옮긴 이유가 바로 그것이다.


def _length(node_id: str = "n1", max_chars: int = 100) -> Node:
    return Node(id=node_id, type=NodeType.LENGTH, config={"max_chars": max_chars})


def _transform(node_id: str = "n1", op: str = "lower") -> Node:
    return Node(id=node_id, type=NodeType.TRANSFORM, config={"op": op})


def test_extract_may_not_have_inputs():
    """extract 는 소스다. 무언가를 읽는 extract 는 의미가 없다."""
    with pytest.raises(ValidationError) as info:
        _draft(
            nodes=(_extract("a"), _extract("b")),
            edges=(Edge("a", "b"),),
        ).validate()
    assert info.value.code == "GUARDRAIL-012"
    assert info.value.details["node_id"] == "b"


@pytest.mark.parametrize("factory", [_regex, _length, _transform])
def test_a_single_input_node_rejects_zero_inputs(factory):
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(factory("solo"),), edges=()).validate()
    assert info.value.code == "GUARDRAIL-012"
    assert info.value.details["node_id"] == "solo"


@pytest.mark.parametrize("factory", [_regex, _length, _transform])
def test_a_single_input_node_rejects_two_inputs(factory):
    """입력이 둘이면 어느 텍스트를 볼지 정할 수 없다."""
    with pytest.raises(ValidationError) as info:
        _draft(
            nodes=(_extract("a"), _extract("b", "output"), factory("mid")),
            edges=(Edge("a", "mid"), Edge("b", "mid")),
        ).validate()
    assert info.value.code == "GUARDRAIL-012"
    assert info.value.details["node_id"] == "mid"


@pytest.mark.parametrize("factory", [_regex, _length, _transform])
def test_a_single_input_node_accepts_one_input(factory):
    _draft(
        nodes=(_extract("a"), factory("mid"), _verdict("v")),
        edges=(Edge("a", "mid"), Edge("mid", "v")),
    ).validate()


def test_verdict_requires_at_least_one_input():
    """읽을 것이 없는 판정은 영원히 걸리지 않는다."""
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_verdict("v"),), edges=()).validate()
    assert info.value.code == "GUARDRAIL-012"
    assert info.value.details["node_id"] == "v"


def test_verdict_accepts_many_inputs():
    """여러 입력은 OR 다 — 하나라도 걸리면 판정이 선다."""
    _draft(
        nodes=(_extract("a"), _regex("r1"), _length("l1"), _verdict("v")),
        edges=(Edge("a", "r1"), Edge("a", "l1"), Edge("r1", "v"), Edge("l1", "v")),
    ).validate()


def test_the_arity_error_reports_the_expected_count():
    """UI 가 무엇이 틀렸는지 말해줄 수 있어야 한다."""
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_regex("solo"),), edges=()).validate()
    assert info.value.details["inputs"] == 0
    assert "1" in info.value.details["expected"]


def test_an_empty_graph_still_validates():
    """노드 0개는 아무것도 하지 않는 가드레일이다 — 2a 의 성질을 유지한다."""
    _draft(nodes=(), edges=()).validate()


def test_arity_does_not_count_outgoing_edges():
    """전개(fan-out)는 정상이다 — 한 extract 를 여러 체크가 읽는다."""
    _draft(
        nodes=(_extract("a"), _regex("r1"), _regex("r2"), _verdict("v")),
        edges=(Edge("a", "r1"), Edge("a", "r2"), Edge("r1", "v"), Edge("r2", "v")),
    ).validate()


def test_a_bad_config_is_reported_before_arity():
    """노드 설정 오류가 arity 보다 먼저 나와야 한다.

    그러지 않으면 설정만 확인하려는 테스트와 UI 피드백이 전부 GUARDRAIL-012 로
    덮여버린다 — 저작자는 오타를 고칠 방법을 알 수 없게 된다.
    """
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_regex("bad", "[unclosed"),), edges=()).validate()
    assert info.value.code == "GUARDRAIL-005"


# --- ②④ 체크포인트 + 오염 노드 ---------------------------------------------
#
# §8 의 공격은 ①도 ③도 정상이다 — ②로 들어와 ④로 나간다.


def _taint(node_id: str = "t", checkpoint: str = "tool_call") -> Node:
    return Node(id=node_id, type=NodeType.TAINT, config={"checkpoint": checkpoint})


def _all(node_id: str = "a") -> Node:
    return Node(id=node_id, type=NodeType.ALL, config={})


@pytest.mark.parametrize("checkpoint", ["input", "output", "tool_result", "tool_call"])
def test_every_checkpoint_is_valid(checkpoint):
    _draft(nodes=(_extract("e", checkpoint),), edges=()).validate()


def test_an_unknown_checkpoint_is_still_rejected():
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_extract("e", "nowhere"),), edges=()).validate()
    assert info.value.code == "GUARDRAIL-005"


def test_taint_requires_a_checkpoint():
    """taint 만 조상인 부분 그래프를 어디서 실행할지 정할 수 없다."""
    node = Node(id="t", type=NodeType.TAINT, config={})
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(node,), edges=()).validate()
    assert info.value.code == "GUARDRAIL-005"
    assert info.value.details["node_id"] == "t"


def test_taint_rejects_an_unknown_checkpoint():
    with pytest.raises(ValidationError):
        _draft(nodes=(_taint("t", "nowhere"),), edges=()).validate()


def test_taint_may_not_have_inputs():
    """소스다. extract 와 같은 자리."""
    with pytest.raises(ValidationError) as info:
        _draft(
            nodes=(_extract("e"), _taint("t")),
            edges=(Edge("e", "t"),),
        ).validate()
    assert info.value.code == "GUARDRAIL-012"
    assert info.value.details["node_id"] == "t"


def test_a_taint_only_graph_validates():
    """extract 가 없어도 유효하다 — 오염은 텍스트가 아니라 구조적 사실이다."""
    _draft(nodes=(_taint("t"), _verdict("v")), edges=(Edge("t", "v"),)).validate()


def test_all_requires_at_least_two_inputs():
    """입력이 하나면 AND 가 무의미하다 — 저작자가 뭔가 잘못 그린 것이다."""
    with pytest.raises(ValidationError) as info:
        _draft(
            nodes=(_taint("t"), _all("a"), _verdict("v")),
            edges=(Edge("t", "a"), Edge("a", "v")),
        ).validate()
    assert info.value.code == "GUARDRAIL-012"
    assert info.value.details["node_id"] == "a"


def test_all_rejects_zero_inputs():
    with pytest.raises(ValidationError) as info:
        _draft(nodes=(_all("a"), _verdict("v")), edges=(Edge("a", "v"),)).validate()
    assert info.value.code == "GUARDRAIL-012"


def test_all_accepts_two_inputs():
    """§8 2단계의 모양: 오염됨 AND 부작용 툴."""
    _draft(
        nodes=(_taint("t"), _extract("e", "tool_call"), _regex("r"), _all("a"), _verdict("v")),
        edges=(
            Edge("e", "r"),
            Edge("t", "a"),
            Edge("r", "a"),
            Edge("a", "v"),
        ),
    ).validate()


def test_all_accepts_three_inputs():
    _draft(
        nodes=(
            _taint("t"),
            _extract("e", "tool_call"),
            _regex("r1", "aa"),
            _regex("r2", "bb"),
            _all("a"),
            _verdict("v"),
        ),
        edges=(
            Edge("e", "r1"),
            Edge("e", "r2"),
            Edge("t", "a"),
            Edge("r1", "a"),
            Edge("r2", "a"),
            Edge("a", "v"),
        ),
    ).validate()


def test_all_takes_no_config():
    """설정이 늘어나면 저장된 그래프가 그만큼 깨질 여지가 생긴다."""
    _draft(
        nodes=(_taint("t"), _taint("t2", "tool_result"), _all("a"), _verdict("v")),
        edges=(Edge("t", "a"), Edge("t2", "a"), Edge("a", "v")),
    )


def test_node_type_values_are_stable():
    """저장된 그래프에 문자열로 남으므로 계약이다."""
    assert NodeType.EXTRACT == "extract"
    assert NodeType.REGEX == "regex"
    assert NodeType.LENGTH == "length"
    assert NodeType.TRANSFORM == "transform"
    assert NodeType.VERDICT == "verdict"
    assert NodeType.TAINT == "taint"
    assert NodeType.ALL == "all"
