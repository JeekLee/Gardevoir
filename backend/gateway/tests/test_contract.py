import orjson
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from gateway.contract import (
    API_PREFIX,
    EXTENSION_KEY,
    HEADER_ACTION,
    HEADER_AUDIT_ID,
    HEADER_GUARDRAIL,
    HEADER_GUARDRAIL_VERSION,
    HEADER_LATENCY_MS,
    HEADER_MODE,
    HEADER_REQUEST_ID,
    STANDARD_FINISH_REASONS,
    Action,
    Mode,
    build_extension,
    response_headers,
)


def test_header_names_are_exact():
    assert HEADER_GUARDRAIL == "X-Gardevoir-Guardrail"
    assert HEADER_MODE == "X-Gardevoir-Mode"
    assert HEADER_ACTION == "X-Gardevoir-Action"
    assert HEADER_GUARDRAIL_VERSION == "X-Gardevoir-Guardrail-Version"
    assert HEADER_AUDIT_ID == "X-Gardevoir-Audit-Id"
    assert HEADER_LATENCY_MS == "X-Gardevoir-Latency-Ms"
    assert HEADER_REQUEST_ID == "X-Request-Id"
    assert EXTENSION_KEY == "gardevoir"
    assert API_PREFIX == "/v1"


def test_no_protocol_version_header_exists():
    """계약 버전은 URL 접두어(/v1)가 담당한다. 헤더를 두면 호출처가 관리해야 한다."""
    import gateway.contract as c

    assert not [n for n in dir(c) if "PROTOCOL" in n.upper()]


def test_mode_parse_never_fails_open():
    assert Mode.parse(None) is Mode.ENFORCE
    assert Mode.parse("") is Mode.ENFORCE
    assert Mode.parse("enforce") is Mode.ENFORCE
    assert Mode.parse("dry-run") is Mode.DRY_RUN
    assert Mode.parse("DRY-RUN") is Mode.DRY_RUN
    assert Mode.parse("  dry-run  ") is Mode.DRY_RUN
    # 알 수 없는 값은 시행으로 떨어진다 — 우회 수단이 되어서는 안 된다
    assert Mode.parse("nonsense") is Mode.ENFORCE
    assert Mode.parse("off") is Mode.ENFORCE


def test_build_extension_shape():
    ext = build_extension(
        action=Action.ALLOW,
        guardrail="doc-agent",
        guardrail_version=0,
        audit_id="evt_1",
        mode=Mode.ENFORCE,
    )
    assert ext == {
        "action": "allow",
        "guardrail": "doc-agent",
        "guardrail_version": 0,
        "mode": "enforce",
        "audit_id": "evt_1",
    }


def test_build_extension_dry_run_reports_would_have():
    ext = build_extension(
        action=Action.ALLOW,
        guardrail="doc-agent",
        guardrail_version=3,
        audit_id="evt_2",
        mode=Mode.DRY_RUN,
        dry_run_would_have={"action": "blocked", "checks": ["kr-rrn"]},
    )
    assert ext["dry_run"] is True
    assert ext["would_have"] == {"action": "blocked", "checks": ["kr-rrn"]}


def test_enforce_mode_carries_no_dry_run_keys():
    ext = build_extension(
        action=Action.ALLOW,
        guardrail="base",
        guardrail_version=0,
        audit_id="evt_3",
        mode=Mode.ENFORCE,
        dry_run_would_have={"action": "blocked"},
    )
    assert "dry_run" not in ext
    assert "would_have" not in ext


def test_response_headers_are_all_strings():
    h = response_headers(
        action=Action.ALLOW,
        guardrail="doc-agent",
        guardrail_version=0,
        mode=Mode.ENFORCE,
        audit_id="evt_4",
        latency_ms=0.6183,
    )
    assert h[HEADER_ACTION] == "allow"
    assert h[HEADER_GUARDRAIL_VERSION] == "0"
    assert h[HEADER_LATENCY_MS] == "0.618"
    assert all(isinstance(v, str) for v in h.values())


def test_response_headers_echo_requested_values():
    """앱이 dry-run을 요청했는데 무시됐다는 것을 알 수 있어야 한다 (§7.2)."""
    h = response_headers(
        action=Action.ALLOW,
        guardrail="internal-analytics",
        guardrail_version=7,
        mode=Mode.DRY_RUN,
        audit_id="evt_5",
        latency_ms=1.0,
    )
    assert h[HEADER_GUARDRAIL] == "internal-analytics"
    assert h[HEADER_MODE] == "dry-run"


# --- §11.9 회귀 테스트: SDK 확장 필드 관용성 ---------------------------------
# OAS 스펙이 자주 바뀌므로 실측을 고정한다. SDK 버전을 올릴 때 관용성이
# 바뀌면 여기서 즉시 실패해야 한다.

_BASE_COMPLETION = {
    "id": "x",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "logprobs": None,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "send_email", "arguments": "{}"},
                    }
                ],
            },
        }
    ],
}


def test_sdk_tolerates_extension_object_on_completion():
    payload = dict(
        _BASE_COMPLETION,
        gardevoir={"action": "approval_required", "audit_id": "evt_6"},
    )
    parsed = ChatCompletion.model_validate(payload)
    assert parsed.gardevoir["action"] == "approval_required"


def test_sdk_tolerates_extension_object_on_chunk():
    chunk = {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "delta": {"content": "hi"},
                "finish_reason": None,
                "logprobs": None,
            }
        ],
        "gardevoir": {"action": "blocked", "guardrail_version": 37},
    }
    parsed = ChatCompletionChunk.model_validate(chunk)
    assert parsed.gardevoir["guardrail_version"] == 37


def test_sdk_rejects_custom_finish_reason():
    """커스텀 finish_reason은 SDK를 깨뜨린다. 표준 값만 써야 하는 근거."""
    payload = dict(_BASE_COMPLETION)
    payload["choices"] = [
        dict(_BASE_COMPLETION["choices"][0], finish_reason="guard_approval_required")
    ]
    with pytest.raises(Exception) as exc:
        ChatCompletion.model_validate(payload)
    assert "finish_reason" in str(exc.value)


def test_standard_finish_reasons_match_sdk_literal():
    assert STANDARD_FINISH_REASONS == frozenset(
        {"stop", "length", "tool_calls", "content_filter", "function_call"}
    )
    for reason in STANDARD_FINISH_REASONS:
        payload = dict(_BASE_COMPLETION)
        payload["choices"] = [dict(_BASE_COMPLETION["choices"][0], finish_reason=reason)]
        ChatCompletion.model_validate(payload)  # 예외가 나면 실패


def test_extension_survives_orjson_roundtrip():
    ext = build_extension(
        action=Action.BLOCKED,
        guardrail="base",
        guardrail_version=1,
        audit_id="evt_7",
        mode=Mode.ENFORCE,
    )
    payload = dict(_BASE_COMPLETION, **{EXTENSION_KEY: ext})
    restored = orjson.loads(orjson.dumps(payload))
    assert ChatCompletion.model_validate(restored).gardevoir["action"] == "blocked"
