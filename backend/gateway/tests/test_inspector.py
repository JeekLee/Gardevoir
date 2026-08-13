"""체크포인트 검사 — 계획을 실제 페이로드에 적용한다.

계획은 컴파일러를 거쳐 만든다. 손으로 조립하면 컴파일러와 검사기가 서로 어긋나도
둘 다 초록색이 된다.
"""

import pytest

from gateway.application.inspection.inspector import Inspector
from gateway.application.inspection.outcome import MASK_PLACEHOLDER, TIER_NONE, TIER_RULES
from gateway.application.plan.compiler import compile_guardrail
from gateway.contract import Action, Mode
from gateway.domain.models.guardrail import Edge, Guardrail, Node, NodeType

RRN = r"\d{6}-\d{7}"


def _node(node_id: str, node_type: NodeType, **config) -> Node:
    return Node(id=node_id, type=node_type, config=config)


def _guardrail(nodes, edges, *, name: str = "doc-agent", version_number: int = 3) -> Guardrail:
    guardrail = Guardrail(
        name=name,
        version=str(version_number),
        version_number=version_number,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )
    guardrail.validate()
    return guardrail


def _checkpoint_plan(checkpoint: str, *, pattern: str = "alpha", action: str = "block"):
    return compile_guardrail(
        _guardrail(
            (
                _node("e", NodeType.EXTRACT, checkpoint=checkpoint),
                _node("r", NodeType.REGEX, pattern=pattern),
                _node("v", NodeType.VERDICT, decision="conclusive", action=action),
            ),
            (Edge("e", "r"), Edge("r", "v")),
        )
    )


class StubRegistry:
    def __init__(self, plans: dict | None = None) -> None:
        self._plans = plans or {}
        self.gets = 0

    def get(self, name: str):
        self.gets += 1
        return self._plans.get(name)


def _inspector(**plans) -> Inspector:
    return Inspector(plans=StubRegistry(dict(plans)))


def _payload(*contents) -> dict:
    return {"messages": [{"role": "user", "content": c} for c in contents]}


def _completion(*contents) -> dict:
    return {
        "choices": [
            {"index": i, "finish_reason": "stop", "message": {"role": "assistant", "content": c}}
            for i, c in enumerate(contents)
        ]
    }


# --- 계획 없음 ---------------------------------------------------------------


def test_no_plan_inspects_nothing():
    """발행본이 없으면 통과시키되 검사하지 않았다는 것이 드러나야 한다."""
    inspector = _inspector()
    assert inspector.plan_for("missing") is None

    result = inspector.input(None, _payload("900101-1234567"), mode=Mode.ENFORCE)
    assert result.action is Action.ALLOW
    assert result.ran is False
    assert result.tier == TIER_NONE


def test_a_plan_without_that_checkpoint_inspects_nothing():
    """입력만 보는 가드레일은 출력 체크포인트를 건너뛴다."""
    plan = _checkpoint_plan("input")
    result = _inspector().output(plan, _completion("900101-1234567"), mode=Mode.ENFORCE)
    assert result.ran is False


def test_plan_for_reads_the_registry():
    registry = StubRegistry({"doc-agent": _checkpoint_plan("input")})
    inspector = Inspector(plans=registry)
    assert inspector.plan_for("doc-agent") is not None
    assert registry.gets == 1


# --- 입력 (①) ---------------------------------------------------------------


def test_a_clean_input_is_allowed():
    plan = _checkpoint_plan("input")
    result = _inspector().input(plan, _payload("hello"), mode=Mode.ENFORCE)
    assert result.action is Action.ALLOW
    assert result.ran is True
    assert result.tier == TIER_RULES
    assert result.checks_fired == ()


def test_a_dirty_input_is_blocked():
    plan = _checkpoint_plan("input")
    result = _inspector().input(plan, _payload("alpha"), mode=Mode.ENFORCE)
    assert result.action is Action.BLOCKED
    assert result.blocked is True
    assert result.checks_fired == ("v",)


def test_input_checks_every_user_message():
    """messages 는 매 턴 전체로 온다 — 이전 턴에 심은 것도 걸려야 한다."""
    plan = _checkpoint_plan("input")
    result = _inspector().input(plan, _payload("alpha", "innocent"), mode=Mode.ENFORCE)
    assert result.blocked is True


def test_an_empty_input_is_allowed():
    plan = _checkpoint_plan("input")
    assert _inspector().input(plan, {}, mode=Mode.ENFORCE).action is Action.ALLOW


# --- 출력 (③) ---------------------------------------------------------------


def test_a_clean_output_is_allowed():
    plan = _checkpoint_plan("output")
    body = _completion("all good")
    result = _inspector().output(plan, body, mode=Mode.ENFORCE)
    assert result.action is Action.ALLOW
    assert body["choices"][0]["message"]["content"] == "all good"


def test_a_dirty_output_is_blocked():
    plan = _checkpoint_plan("output")
    result = _inspector().output(plan, _completion("alpha"), mode=Mode.ENFORCE)
    assert result.blocked is True


def test_a_response_without_content_still_counts_as_inspected():
    """tool_calls 응답은 content 가 없다. 검사했다는 사실은 남아야 한다."""
    plan = _checkpoint_plan("output")
    body = {"choices": [{"message": {"role": "assistant", "content": None}}]}
    result = _inspector().output(plan, body, mode=Mode.ENFORCE)
    assert result.ran is True
    assert result.action is Action.ALLOW


def test_output_checks_every_choice():
    plan = _checkpoint_plan("output")
    result = _inspector().output(plan, _completion("clean", "alpha"), mode=Mode.ENFORCE)
    assert result.blocked is True


# --- 마스킹 ------------------------------------------------------------------


def _mask_plan(pattern: str = RRN):
    return _checkpoint_plan("output", pattern=pattern, action="mask")


def test_output_masking_replaces_the_span():
    body = _completion("고객 번호는 900101-1234567 입니다")
    result = _inspector().output(_mask_plan(), body, mode=Mode.ENFORCE)

    assert result.masked is True
    assert result.action is Action.ALLOW, "마스킹은 차단이 아니다"
    assert body["choices"][0]["message"]["content"] == f"고객 번호는 {MASK_PLACEHOLDER} 입니다"


def test_masking_keeps_the_rest_of_the_text():
    body = _completion("before 900101-1234567 after")
    _inspector().output(_mask_plan(), body, mode=Mode.ENFORCE)
    content = body["choices"][0]["message"]["content"]
    assert content.startswith("before ")
    assert content.endswith(" after")


def test_masking_replaces_every_occurrence():
    body = _completion("900101-1234567 and 900102-7654321")
    _inspector().output(_mask_plan(), body, mode=Mode.ENFORCE)
    assert body["choices"][0]["message"]["content"] == f"{MASK_PLACEHOLDER} and {MASK_PLACEHOLDER}"


def test_masking_applies_to_every_choice():
    body = _completion("900101-1234567", "900102-7654321")
    _inspector().output(_mask_plan(), body, mode=Mode.ENFORCE)
    assert body["choices"][0]["message"]["content"] == MASK_PLACEHOLDER
    assert body["choices"][1]["message"]["content"] == MASK_PLACEHOLDER


def test_a_clean_choice_is_untouched_when_another_is_masked():
    body = _completion("nothing here", "900101-1234567")
    _inspector().output(_mask_plan(), body, mode=Mode.ENFORCE)
    assert body["choices"][0]["message"]["content"] == "nothing here"


def test_masking_preserves_multimodal_shape():
    """문자열로 합쳐 되쓰면 응답 모양이 바뀌어 SDK 가 깨진다."""
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "id 900101-1234567"},
                        {"type": "text", "text": "kept"},
                    ],
                }
            }
        ]
    }
    result = _inspector().output(_mask_plan(), body, mode=Mode.ENFORCE)
    content = body["choices"][0]["message"]["content"]
    assert result.masked is True
    assert isinstance(content, list)
    assert content[0]["text"] == f"id {MASK_PLACEHOLDER}"
    assert content[1]["text"] == "kept"


def test_masking_only_applies_the_fired_verdicts_patterns():
    """계획의 모든 패턴을 돌리면 마스킹 판정과 무관한 패턴까지 가려진다.

    두 번째 판정을 allow 로 둔다 — block 이면 우선순위에서 이겨서 마스킹 자체가
    돌지 않으므로 이 성질을 볼 수 없다.
    """
    plan = compile_guardrail(
        _guardrail(
            (
                _node("e", NodeType.EXTRACT, checkpoint="output"),
                _node("r_mask", NodeType.REGEX, pattern=RRN),
                _node("r_other", NodeType.REGEX, pattern="SECRET"),
                _node("v_mask", NodeType.VERDICT, decision="conclusive", action="mask"),
                _node("v_allow", NodeType.VERDICT, decision="conclusive", action="allow"),
            ),
            (
                Edge("e", "r_mask"),
                Edge("e", "r_other"),
                Edge("r_mask", "v_mask"),
                Edge("r_other", "v_allow"),
            ),
        )
    )
    body = _completion("900101-1234567 and the word SECRET")
    result = _inspector().output(plan, body, mode=Mode.ENFORCE)
    assert result.masked is True

    content = body["choices"][0]["message"]["content"]
    assert MASK_PLACEHOLDER in content
    assert "SECRET" in content, "마스킹 판정이 읽지 않는 패턴까지 가렸다"


def test_a_mask_that_matches_nothing_does_not_claim_masked(caplog):
    """action=mask 라고 말하면서 원문을 내보내는 것이 조용한 fail-open 이다.

    컴파일러 제한 덕분에 정상적으로는 올 수 없는 상태다. 그래도 거짓 보고를 하지
    않는지 고정한다 — 나중에 제한이 느슨해지면 여기서 드러난다.
    """
    plan = _mask_plan()
    program = plan.program_for("output")
    assert program is not None
    # 판정은 걸리게 두고 마스킹용 패턴만 비운다
    object.__setattr__(program, "patterns_by_slot", {})

    body = _completion("900101-1234567")
    result = _inspector().output(plan, body, mode=Mode.ENFORCE)
    assert result.masked is False
    assert body["choices"][0]["message"]["content"] == "900101-1234567"


def test_block_beats_mask_on_output():
    plan = compile_guardrail(
        _guardrail(
            (
                _node("e", NodeType.EXTRACT, checkpoint="output"),
                _node("r_mask", NodeType.REGEX, pattern=RRN),
                _node("r_block", NodeType.REGEX, pattern="SECRET"),
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
    )
    result = _inspector().output(plan, _completion("900101-1234567 SECRET"), mode=Mode.ENFORCE)
    assert result.blocked is True


# --- dry-run -----------------------------------------------------------------


def test_dry_run_never_blocks_the_input():
    plan = _checkpoint_plan("input")
    result = _inspector().input(plan, _payload("alpha"), mode=Mode.DRY_RUN)
    assert result.action is Action.ALLOW
    assert result.would_have is Action.BLOCKED
    assert result.checks_fired == ("v",)


def test_dry_run_never_blocks_the_output():
    plan = _checkpoint_plan("output")
    result = _inspector().output(plan, _completion("alpha"), mode=Mode.DRY_RUN)
    assert result.action is Action.ALLOW
    assert result.would_have is Action.BLOCKED


def test_dry_run_does_not_mask():
    """시험 중에 응답을 바꾸면 시험이 아니다."""
    body = _completion("900101-1234567")
    result = _inspector().output(_mask_plan(), body, mode=Mode.DRY_RUN)
    assert result.masked is False
    assert body["choices"][0]["message"]["content"] == "900101-1234567"


def test_a_clean_dry_run_reports_no_would_have():
    plan = _checkpoint_plan("input")
    result = _inspector().input(plan, _payload("hello"), mode=Mode.DRY_RUN)
    assert result.would_have is None


def test_dry_run_collects_every_check():
    """튜닝이 존재 이유다 — 조기 종료하면 오탐을 찾을 수 없다 (§4)."""
    plan = compile_guardrail(
        _guardrail(
            (
                _node("e", NodeType.EXTRACT, checkpoint="input"),
                _node("r1", NodeType.REGEX, pattern="alpha"),
                _node("r2", NodeType.REGEX, pattern="bravo"),
                _node("v1", NodeType.VERDICT, decision="conclusive", action="block"),
                _node("v2", NodeType.VERDICT, decision="conclusive", action="block"),
            ),
            (Edge("e", "r1"), Edge("e", "r2"), Edge("r1", "v1"), Edge("r2", "v2")),
        )
    )
    enforced = _inspector().input(plan, _payload("alpha bravo"), mode=Mode.ENFORCE)
    dry = _inspector().input(plan, _payload("alpha bravo"), mode=Mode.DRY_RUN)

    assert enforced.checks_fired == ("v1",)
    assert sorted(dry.checks_fired) == ["v1", "v2"]


# --- 2티어 -------------------------------------------------------------------


def test_pending_model_is_carried():
    """Phase 4 가 받을 자리. 규칙이 스스로 판정하지 않는다 (§4)."""
    plan = _checkpoint_plan("input", action="block")
    hinting = compile_guardrail(
        _guardrail(
            (
                _node("e", NodeType.EXTRACT, checkpoint="input"),
                _node("r", NodeType.REGEX, pattern="alpha"),
                _node("v", NodeType.VERDICT, decision="hint", action="block"),
            ),
            (Edge("e", "r"), Edge("r", "v")),
        )
    )
    assert _inspector().input(plan, _payload("alpha"), mode=Mode.ENFORCE).blocked is True

    result = _inspector().input(hinting, _payload("alpha"), mode=Mode.ENFORCE)
    assert result.action is Action.ALLOW, "모델 없이 규칙이 막아서는 안 된다"
    assert result.pending_model == ("v",)


# --- 계획 일관성 -------------------------------------------------------------


def test_the_same_plan_object_serves_both_checkpoints():
    """요청 하나는 시작할 때 잡은 계획을 끝까지 쓴다 (§6)."""
    plan = compile_guardrail(
        _guardrail(
            (
                _node("ei", NodeType.EXTRACT, checkpoint="input"),
                _node("ri", NodeType.REGEX, pattern="alpha"),
                _node("vi", NodeType.VERDICT, decision="conclusive", action="block"),
                _node("eo", NodeType.EXTRACT, checkpoint="output"),
                _node("ro", NodeType.REGEX, pattern="bravo"),
                _node("vo", NodeType.VERDICT, decision="conclusive", action="block"),
            ),
            (
                Edge("ei", "ri"),
                Edge("ri", "vi"),
                Edge("eo", "ro"),
                Edge("ro", "vo"),
            ),
        )
    )
    registry = StubRegistry({"doc-agent": plan})
    inspector = Inspector(plans=registry)

    held = inspector.plan_for("doc-agent")
    assert inspector.input(held, _payload("clean"), mode=Mode.ENFORCE).ran is True
    assert inspector.output(held, _completion("bravo"), mode=Mode.ENFORCE).blocked is True
    assert registry.gets == 1, "체크포인트마다 레지스트리를 다시 읽었다"


@pytest.mark.parametrize("mode", [Mode.ENFORCE, Mode.DRY_RUN])
def test_inspection_does_not_mutate_the_request_payload(mode):
    import orjson

    plan = _checkpoint_plan("input")
    payload = _payload("alpha")
    before = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    _inspector().input(plan, payload, mode=mode)
    assert orjson.dumps(payload, option=orjson.OPT_SORT_KEYS) == before
