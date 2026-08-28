"""General source/check grammar for tool-call inspection."""

import pytest

import gateway.guardrail.application.service.inspector as inspector_module
from gateway.guardrail.application.compiler import compile_guardrail
from gateway.guardrail.application.provenance import (
    parse_argument_strings,
    tool_extract_text,
)
from gateway.guardrail.application.service.inspector import Inspector
from gateway.guardrail.domain.executor import Subject, execute
from gateway.guardrail.domain.models.guardrail import Guardrail, VerdictAction
from gateway.guardrail.domain.models.mode import Mode


def _plan(*, nodes: list[dict], edges: list[tuple[str, str]]):
    guardrail = Guardrail.draft(
        name="tool-node-redesign",
        description="",
        graph={
            "nodes": nodes,
            "edges": [{"src": src, "dst": dst} for src, dst in edges],
        },
    )
    guardrail.validate()
    return compile_guardrail(guardrail)


def _tool_plan(
    *,
    field: str = "name",
    pattern: str = ".",
    tools: dict | None = None,
):
    config: dict = {"field": field}
    if tools is not None:
        config["tools"] = tools
    return _plan(
        nodes=[
            {"id": "source", "type": "tool_extract", "config": config},
            {"id": "regex", "type": "regex", "config": {"pattern": pattern}},
            {"id": "block", "type": "verdict", "config": {"action": "block"}},
        ],
        edges=[("source", "regex"), ("regex", "block")],
    )


def _call(*, name: object = "send_email", arguments: object = None) -> dict:
    function = {"arguments": arguments if arguments is not None else "{}"}
    if name is not None:
        function["name"] = name
    return {"type": "function", "function": function}


def _body(*calls: dict) -> dict:
    return {"choices": [{"message": {"tool_calls": list(calls)}}]}


def _inspect(plan, *calls: dict, payload: object | None = None):
    return Inspector(plans=None).tool_call(  # type: ignore[arg-type]
        plan,
        _body(*calls),
        payload or {"messages": []},
        mode=Mode.ENFORCE,
    )


@pytest.mark.parametrize(
    ("tools", "name", "expected"),
    [
        (None, "new_tool", VerdictAction.BLOCK),
        ({"exclude": ["read_file"]}, "read_file", VerdictAction.ALLOW),
        ({"exclude": ["read_file"]}, "new_tool", VerdictAction.BLOCK),
        ({"include": ["delete_files"]}, "delete_files", VerdictAction.BLOCK),
        ({"include": ["delete_files"]}, "send_email", VerdictAction.ALLOW),
        ({"include": ["delete_files"]}, None, VerdictAction.BLOCK),
    ],
)
def test_tool_selector_defaults_and_missing_name_fail_safe(
    tools: dict | None,
    name: str | None,
    expected: VerdictAction,
) -> None:
    """exclude 기본값과 이름 누락은 새 툴이 검사에서 빠지는 fail-open을 막는다."""
    inspection = _inspect(_tool_plan(tools=tools), _call(name=name))

    assert inspection.action is expected


def test_unselected_tool_call_does_not_execute_program(monkeypatch: pytest.MonkeyPatch) -> None:
    """선택자에서 제외된 호출은 슬롯 프로그램 자체를 실행하지 않는다."""
    plan = _tool_plan(tools={"exclude": ["read_file"]})

    def unexpected_execute(*args, **kwargs):
        pytest.fail("unselected tool call executed the program")

    monkeypatch.setattr(inspector_module, "execute", unexpected_execute)

    assert _inspect(plan, _call(name="read_file")).action is VerdictAction.ALLOW


def test_tool_extract_arguments_joins_only_string_values() -> None:
    """arguments는 키·따옴표 없이 문자열 값만 선언 순서대로 잇는다."""
    call = _call(
        arguments={
            "to": "a@b.com",
            "count": 3,
            "payload": {"subject": "안녕", "meta": {"id": "AB-12345"}},
        }
    )

    assert (
        tool_extract_text("send_email", parse_argument_strings(call), "arguments")
        == "a@b.com 안녕 AB-12345"
    )


@pytest.mark.parametrize(
    ("field", "pattern", "expected"),
    [
        ("name", "^send_email$", VerdictAction.BLOCK),
        ("arguments", r"\d{6}-\d{7}", VerdictAction.BLOCK),
        ("to", r"^a@b\.com$", VerdictAction.BLOCK),
        ("cc[*]", r"^x@y\.com y@y\.com$", VerdictAction.BLOCK),
        ("payload.meta.id", "^AB-12345$", VerdictAction.BLOCK),
        ("missing.path", ".", VerdictAction.ALLOW),
    ],
)
def test_tool_extract_fields_feed_regex(field: str, pattern: str, expected: VerdictAction) -> None:
    """name·arguments·중첩 경로·배열 와일드카드가 일반 regex 입력으로 동작한다."""
    call = _call(
        arguments={
            "to": "a@b.com",
            "cc": ["x@y.com", "y@y.com"],
            "payload": {"rrn": "900101-1234567", "meta": {"id": "AB-12345"}},
        }
    )

    assert _inspect(_tool_plan(field=field, pattern=pattern), call).action is expected


def test_malformed_arguments_are_empty_and_visible_in_audit_evidence() -> None:
    """인수 JSON 오류는 통과시키되 감사 evidence에서 숨기지 않는다."""
    inspection = _inspect(
        _tool_plan(field="arguments", pattern=r"\d{6}-\d{7}"),
        _call(arguments='{"rrn":'),
    )

    assert inspection.action is VerdictAction.ALLOW
    assert inspection.evidence == (
        {"tool": "send_email", "arguments": [], "arguments_parse_failed": True},
    )


def test_extract_reads_tool_result_at_tool_call() -> None:
    """extract의 from과 at이 달라도 해당 체크포인트 프로그램에서 출처를 읽는다."""
    plan = _plan(
        nodes=[
            {
                "id": "external",
                "type": "extract",
                "config": {"from": "tool_result", "at": "tool_call"},
            },
            {"id": "present", "type": "regex", "config": {"pattern": "."}},
            {"id": "block", "type": "verdict", "config": {"action": "block"}},
        ],
        edges=[("external", "present"), ("present", "block")],
    )
    payload = {"messages": [{"role": "tool", "content": "external data"}]}

    assert _inspect(plan, _call(), payload=payload).action is VerdictAction.BLOCK


def test_not_negates_booleans_and_preserves_pending() -> None:
    """NOT은 True/False만 뒤집고 모델 PENDING은 그대로 verdict에 전달한다."""
    rule_plan = _plan(
        nodes=[
            {
                "id": "source",
                "type": "extract",
                "config": {"from": "user_text", "at": "input"},
            },
            {"id": "regex", "type": "regex", "config": {"pattern": "secret"}},
            {"id": "not", "type": "not", "config": {}},
            {"id": "block", "type": "verdict", "config": {"action": "block"}},
        ],
        edges=[("source", "regex"), ("regex", "not"), ("not", "block")],
    ).program_for("input")
    assert rule_plan is not None
    assert execute(rule_plan, Subject(user_text="secret")).action is VerdictAction.ALLOW
    assert execute(rule_plan, Subject(user_text="ordinary")).action is VerdictAction.BLOCK

    model_plan = _plan(
        nodes=[
            {
                "id": "source",
                "type": "extract",
                "config": {"from": "user_text", "at": "input"},
            },
            {
                "id": "model",
                "type": "model",
                "config": {"checkpoint": "input", "policy": "Is this sensitive?"},
            },
            {"id": "not", "type": "not", "config": {}},
            {"id": "block", "type": "verdict", "config": {"action": "block"}},
        ],
        edges=[("source", "model"), ("model", "not"), ("not", "block")],
    ).program_for("input")
    assert model_plan is not None
    result = execute(model_plan, Subject(user_text="anything"))
    assert result.action is VerdictAction.ALLOW
    assert result.pending_model == ("block",)


def test_one_blocked_tool_call_blocks_the_whole_response() -> None:
    """복수 tool_call 중 하나만 주민번호를 담아도 응답 전체를 차단한다."""
    inspection = _inspect(
        _tool_plan(field="arguments", pattern=r"\d{6}-\d{7}"),
        _call(name="read_file", arguments={"path": "/tmp/report"}),
        _call(name="send_email", arguments={"body": "900101-1234567"}),
    )

    assert inspection.action is VerdictAction.BLOCK
    assert inspection.checks_fired == ("block",)
    assert inspection.evidence == ({"tool": "send_email", "arguments": ["body"]},)
