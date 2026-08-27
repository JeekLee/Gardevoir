"""§5 node roles and the compiled three-state execution contract."""

import pytest

from gateway.guardrail.application.compiler import compile_guardrail
from gateway.guardrail.domain.executor import Subject, execute
from gateway.guardrail.domain.models.guardrail import Guardrail, VerdictAction
from shared_kernel.exception import AppError


def _plan(*, nodes: list[dict], edges: list[tuple[str, str]]):
    guardrail = Guardrail.draft(
        name="node-model",
        description="",
        graph={
            "nodes": nodes,
            "edges": [{"src": src, "dst": dst} for src, dst in edges],
        },
    )
    guardrail.validate()
    return compile_guardrail(guardrail)


def _extract() -> dict:
    return {"id": "extract", "type": "extract", "config": {"checkpoint": "input"}}


def _model(node_id: str = "model") -> dict:
    return {
        "id": node_id,
        "type": "model",
        "config": {"checkpoint": "input", "policy": "Block requests containing a secret"},
    }


def _verdict(
    *, action: str = "block", combine: str | None = None, decision: str | None = None
) -> dict:
    config = {"action": action}
    if combine is not None:
        config["combine"] = combine
    if decision is not None:
        config["decision"] = decision
    return {"id": "verdict", "type": "verdict", "config": config}


@pytest.mark.parametrize("action", ["block", "mask", "allow"])
def test_rule_only_verdict_ignores_legacy_decision(action: str) -> None:
    """기존 decision 키의 유무가 규칙-only 판정 결과를 바꾸지 않는다."""
    nodes = [
        _extract(),
        {"id": "regex", "type": "regex", "config": {"pattern": "secret"}},
    ]
    edges = [("extract", "regex"), ("regex", "verdict")]
    current = _plan(nodes=[*nodes, _verdict(action=action)], edges=edges).program_for("input")
    legacy = _plan(
        nodes=[*nodes, _verdict(action=action, decision="obsolete-value")], edges=edges
    ).program_for("input")

    assert current is not None
    assert legacy is not None
    for text in ("ordinary request", "contains a secret"):
        assert execute(current, Subject(text=text)) == execute(legacy, Subject(text=text))


def test_model_check_compiles_to_pending_without_applying_action() -> None:
    """모델 호출 전 단계는 verdict를 pending으로 남기고 차단하지 않는다."""
    plan = _plan(
        nodes=[_extract(), _model(), _verdict(decision="model_only")],
        edges=[("extract", "model"), ("model", "verdict")],
    )
    program = plan.program_for("input")

    assert program is not None
    assert plan.model_nodes["verdict"].node_id == "model"
    assert plan.model_nodes["verdict"].policy == "Block requests containing a secret"
    assert plan.model_nodes["verdict"].action is VerdictAction.BLOCK
    assert plan.model_nodes["verdict"].strictness == "strict"
    assert plan.model_nodes["verdict"].model_route == "shieldstral"
    result = execute(program, Subject(text="contains a secret"))
    assert result.action is VerdictAction.ALLOW
    assert result.checks_fired == ()
    assert result.pending_model == ("verdict",)


@pytest.mark.parametrize(
    "config",
    [
        {"checkpoint": "input", "policy": "   "},
        {"checkpoint": "invalid", "policy": "Block secrets"},
        {"checkpoint": "input", "policy": "Block secrets", "strictness": "invalid"},
    ],
)
def test_model_check_rejects_invalid_authoring_config(config: dict) -> None:
    """정책·체크포인트·엄격도 오류는 저작 시점에 422 도메인 오류가 된다."""
    with pytest.raises(AppError) as caught:
        _plan(
            nodes=[
                _extract(),
                {"id": "model", "type": "model", "config": config},
                _verdict(),
            ],
            edges=[("extract", "model"), ("model", "verdict")],
        )

    assert caught.value.code == "GUARDRAIL-005"


def test_model_check_requires_one_input() -> None:
    """MODEL Check는 검사할 extract 입력을 정확히 하나 요구한다."""
    with pytest.raises(AppError) as caught:
        _plan(nodes=[_model(), _verdict()], edges=[("model", "verdict")])

    assert caught.value.code == "GUARDRAIL-012"


@pytest.mark.parametrize(
    ("combine", "text", "expected_fired", "expected_pending"),
    [
        ("any", "contains a secret", ("verdict",), ()),
        ("any", "ordinary request", (), ("verdict",)),
        ("all", "ordinary request", (), ()),
        ("all", "contains a secret", (), ("verdict",)),
    ],
)
def test_verdict_combine_preserves_pending_three_state(
    combine: str,
    text: str,
    expected_fired: tuple[str, ...],
    expected_pending: tuple[str, ...],
) -> None:
    """any/all이 확정 규칙과 PENDING을 3상태 의미대로 합친다."""
    plan = _hint_plan(combine=combine)
    program = plan.program_for("input")

    assert program is not None
    result = execute(program, Subject(text=text))
    assert result.checks_fired == expected_fired
    assert result.pending_model == expected_pending
    assert result.action is (VerdictAction.BLOCK if expected_fired else VerdictAction.ALLOW)


@pytest.mark.parametrize(
    ("combine", "text", "expected_action"),
    [
        ("any", "secret", VerdictAction.BLOCK),
        ("any", "ordinary request", VerdictAction.ALLOW),
        ("all", "secret", VerdictAction.ALLOW),
        ("all", "secret token", VerdictAction.BLOCK),
    ],
)
def test_verdict_combine_rule_only_results(
    combine: str, text: str, expected_action: VerdictAction
) -> None:
    """규칙-only any는 OR, all은 AND로 확정 판정을 낸다."""
    plan = _plan(
        nodes=[
            _extract(),
            {"id": "secret", "type": "regex", "config": {"pattern": "secret"}},
            {"id": "token", "type": "regex", "config": {"pattern": "token"}},
            _verdict(combine=combine),
        ],
        edges=[
            ("extract", "secret"),
            ("extract", "token"),
            ("secret", "verdict"),
            ("token", "verdict"),
        ],
    )
    program = plan.program_for("input")

    assert program is not None
    result = execute(program, Subject(text=text))
    assert result.action is expected_action
    assert result.pending_model == ()


def test_verdict_combine_defaults_to_any() -> None:
    """combine이 없는 기존 verdict는 OR 동작을 유지한다."""
    plan = _plan(
        nodes=[
            _extract(),
            {"id": "first", "type": "regex", "config": {"pattern": "first"}},
            {"id": "second", "type": "regex", "config": {"pattern": "second"}},
            _verdict(),
        ],
        edges=[
            ("extract", "first"),
            ("extract", "second"),
            ("first", "verdict"),
            ("second", "verdict"),
        ],
    )
    program = plan.program_for("input")

    assert program is not None
    assert execute(program, Subject(text="first")).action is VerdictAction.BLOCK


def test_verdict_rejects_unknown_combine() -> None:
    """combine은 any/all 외 값을 저작 시점에 거부한다."""
    with pytest.raises(AppError) as caught:
        _plan(
            nodes=[_extract(), _verdict(combine="invalid")],
            edges=[("extract", "verdict")],
        )

    assert caught.value.code == "GUARDRAIL-005"


def test_multiple_model_checks_for_one_verdict_are_rejected() -> None:
    """한 verdict의 모델 정책 출처가 둘이면 발행 계획을 만들 수 없다."""
    with pytest.raises(AppError) as caught:
        _plan(
            nodes=[
                _extract(),
                _model("model-a"),
                _model("model-b"),
                _verdict(combine="all"),
            ],
            edges=[
                ("extract", "model-a"),
                ("extract", "model-b"),
                ("model-a", "verdict"),
                ("model-b", "verdict"),
            ],
        )

    assert caught.value.code == "GUARDRAIL-017"


def _hint_plan(*, combine: str):
    return _plan(
        nodes=[
            _extract(),
            {"id": "regex", "type": "regex", "config": {"pattern": "secret"}},
            _model(),
            _verdict(combine=combine),
        ],
        edges=[
            ("extract", "regex"),
            ("extract", "model"),
            ("regex", "verdict"),
            ("model", "verdict"),
        ],
    )
