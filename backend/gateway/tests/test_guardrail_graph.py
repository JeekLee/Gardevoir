"""직렬화된 그래프 파싱 — 신뢰할 수 없는 입력이 500 이 되지 않아야 한다."""

import pytest

from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import DRAFT_VERSION, Guardrail, require_valid_name
from shared_kernel.exception import ValidationError

GOOD = {
    "nodes": [
        {"id": "n0", "type": "extract", "config": {"checkpoint": "input"}},
        {"id": "n1", "type": "verdict", "config": {"decision": "conclusive", "action": "block"}},
    ],
    "edges": [{"src": "n0", "dst": "n1"}],
}


def test_draft_builds_from_a_graph():
    g = Guardrail.draft("doc-agent", GOOD)
    assert g.version == DRAFT_VERSION
    assert g.version_number is None
    assert [n.id for n in g.nodes] == ["n0", "n1"]
    assert g.edges[0].src == "n0"
    g.validate()


def test_graph_round_trips():
    assert Guardrail.draft("x", GOOD).to_graph() == GOOD


def test_missing_keys_yield_an_empty_graph():
    g = Guardrail.draft("x", {})
    assert g.nodes == ()
    assert g.edges == ()


def test_null_keys_yield_an_empty_graph():
    g = Guardrail.draft("x", {"nodes": None, "edges": None})
    assert g.nodes == ()
    assert g.edges == ()


@pytest.mark.parametrize(
    "graph",
    [
        {"nodes": "not a list"},
        # 순회 불가능한 값은 TypeError -> 500 이 된다. 문자열은 우연히 순회되므로
        # 이 케이스가 없으면 nodes/edges 타입 검사가 죽어도 테스트가 통과한다.
        {"nodes": 42},
        {"edges": 5},
        {"nodes": True},
        {"edges": {"src": "a"}},
        {"nodes": ["not an object"]},
        {"nodes": [{"type": "regex"}]},
        {"nodes": [{"id": "", "type": "regex"}]},
        {"nodes": [{"id": 7, "type": "regex"}]},
        {"edges": [42]},
        {"edges": [{"src": "a"}]},
        {"edges": [{"src": "a", "dst": ""}]},
    ],
)
def test_malformed_structure_is_a_validation_error(graph):
    with pytest.raises(ValidationError) as exc:
        Guardrail.draft("x", graph)
    assert exc.value.code == GuardrailError.MALFORMED_GRAPH.code


def test_a_non_dict_graph_is_rejected():
    with pytest.raises(ValidationError) as exc:
        Guardrail.draft("x", ["nodes"])  # type: ignore[arg-type]
    assert exc.value.code == GuardrailError.MALFORMED_GRAPH.code


def test_an_unknown_node_type_names_the_node():
    """UI 가 노드를 짚을 수 있어야 한다."""
    with pytest.raises(ValidationError) as exc:
        Guardrail.draft("x", {"nodes": [{"id": "n9", "type": "wasm"}]})
    assert exc.value.code == GuardrailError.INVALID_NODE_CONFIG.code
    assert exc.value.details == {
        "node_id": "n9",
        "reason": (
            "type must be one of "
            "['all', 'extract', 'length', 'provenance', 'regex', 'side_effect', "
            "'taint', 'transform', 'verdict']"
        ),
    }


def test_a_non_object_config_names_the_node():
    with pytest.raises(ValidationError) as exc:
        Guardrail.draft("x", {"nodes": [{"id": "n9", "type": "regex", "config": "abc"}]})
    assert exc.value.code == GuardrailError.INVALID_NODE_CONFIG.code
    assert exc.value.details is not None
    assert exc.value.details["node_id"] == "n9"


def test_a_missing_config_becomes_an_empty_dict():
    """config 가 없으면 노드 검증이 그 사실을 말해야 한다 — KeyError 가 아니라."""
    g = Guardrail.draft("x", {"nodes": [{"id": "n9", "type": "regex"}]})
    assert g.nodes[0].config == {}
    with pytest.raises(ValidationError) as exc:
        g.validate()
    assert exc.value.code == GuardrailError.INVALID_NODE_CONFIG.code


def test_to_graph_lowers_enums_to_strings():
    graph = Guardrail.draft("x", GOOD).to_graph()
    for node in graph["nodes"]:
        assert type(node["type"]) is str
    assert type(graph["nodes"][1]["config"]["action"]) is str


# --- NUL ---------------------------------------------------------------------


def test_a_nul_in_a_config_string_is_rejected():
    """Postgres jsonb 는 \\u0000 을 담지 못한다 — 통과시키면 INSERT 에서 500 이 된다."""
    with pytest.raises(ValidationError) as exc:
        Guardrail.draft("x", {"nodes": [{"id": "n0", "type": "regex", "config": {"p": "a\x00b"}}]})
    assert exc.value.code == GuardrailError.INVALID_NODE_CONFIG.code
    assert exc.value.details["node_id"] == "n0"


def test_a_nul_in_a_nested_config_value_is_rejected():
    graph = {
        "nodes": [
            {"id": "n0", "type": "regex", "config": {"list": [{"deep": "a\x00b"}]}},
        ]
    }
    with pytest.raises(ValidationError) as exc:
        Guardrail.draft("x", graph)
    assert exc.value.code == GuardrailError.INVALID_NODE_CONFIG.code


def test_a_nul_in_a_config_key_is_rejected():
    with pytest.raises(ValidationError):
        Guardrail.draft("x", {"nodes": [{"id": "n0", "type": "regex", "config": {"a\x00b": 1}}]})


def test_a_nul_in_a_node_id_is_rejected():
    with pytest.raises(ValidationError) as exc:
        Guardrail.draft("x", {"nodes": [{"id": "n\x000", "type": "regex", "config": {}}]})
    assert exc.value.code == GuardrailError.INVALID_NODE_CONFIG.code


def test_the_reported_node_id_does_not_carry_the_nul():
    """오류 details 가 그대로 로그·응답에 실린다."""
    with pytest.raises(ValidationError) as exc:
        Guardrail.draft("x", {"nodes": [{"id": "n\x000", "type": "regex", "config": {}}]})
    assert "\x00" not in exc.value.details["node_id"]


def test_an_ordinary_graph_is_untouched_by_the_nul_check():
    Guardrail.draft("x", GOOD).validate()


# --- require_valid_name -----------------------------------------------------


@pytest.mark.parametrize("bad", ["x\x00y", "A", "", "a" * 65, "a/b", None, 7])
def test_require_valid_name_rejects(bad):
    with pytest.raises(ValidationError) as exc:
        require_valid_name(bad)
    assert exc.value.code == GuardrailError.INVALID_NAME.code


def test_require_valid_name_returns_the_name():
    assert require_valid_name("doc-agent") == "doc-agent"


def test_require_valid_name_bounds_what_it_echoes():
    """경로 조각은 몇 KB 일 수도 있다. 오류가 호출자 입력을 그대로 되비추면 안 된다."""
    with pytest.raises(ValidationError) as exc:
        require_valid_name("a" * 5000)
    assert len(exc.value.details["name"]) <= 64


def test_require_valid_name_strips_control_characters_from_the_echo():
    """되비추는 값은 응답 본문과 로그 양쪽에 실린다."""
    with pytest.raises(ValidationError) as exc:
        require_valid_name("a\x00b\ncd")
    assert exc.value.details == {"name": "abcd"}


def test_require_valid_name_does_not_echo_a_non_string():
    with pytest.raises(ValidationError) as exc:
        require_valid_name(object())
    assert exc.value.details == {"name": "object"}
