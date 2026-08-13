"""직렬화된 그래프 파싱 — 신뢰할 수 없는 입력이 500 이 되지 않아야 한다."""

import pytest

from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import DRAFT_VERSION, Guardrail
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
        "reason": "type must be one of ['extract', 'length', 'regex', 'transform', 'verdict']",
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
