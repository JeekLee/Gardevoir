"""스트림 재조립.

④ 검사기가 비스트리밍과 같은 코드를 쓰므로 재조립 결과의 형태가 같아야 한다.
"""

import orjson

from gateway.application.inspection.provenance import (
    argument_strings,
    extract_tool_calls,
    tool_name,
)
from gateway.application.streaming.accumulator import Accumulator


def _chunk(**delta) -> dict:
    return {
        "id": "cmpl-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "gpt-4o",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }


def _finish(reason: str = "stop") -> dict:
    return {
        "id": "cmpl-1",
        "model": "gpt-4o",
        "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
    }


# --- content -----------------------------------------------------------------


def test_content_deltas_accumulate():
    acc = Accumulator()
    assert acc.feed(_chunk(role="assistant", content="")) == ""
    assert acc.feed(_chunk(content="주민번호는 ")) == "주민번호는 "
    assert acc.feed(_chunk(content="900101-")) == "900101-"
    assert acc.content == "주민번호는 900101-"


def test_feed_returns_only_the_new_piece():
    acc = Accumulator()
    acc.feed(_chunk(content="abc"))
    assert acc.feed(_chunk(content="de")) == "de"


def test_a_role_only_first_chunk_becomes_the_template():
    acc = Accumulator()
    acc.feed(_chunk(role="assistant"))
    assert acc.template["id"] == "cmpl-1"
    assert acc.template["model"] == "gpt-4o"
    assert acc.content == ""


def test_the_finish_reason_is_captured():
    acc = Accumulator()
    acc.feed(_chunk(content="hi"))
    acc.feed(_finish("stop"))
    assert acc.finish_reason == "stop"


def test_usage_is_captured():
    """감사에 토큰 수가 필요하다."""
    acc = Accumulator()
    acc.feed({"id": "x", "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    assert acc.usage["prompt_tokens"] == 7


def test_the_model_is_captured():
    acc = Accumulator()
    acc.feed(_chunk(content="hi"))
    assert acc.model == "gpt-4o"


# --- 망가진 청크 -------------------------------------------------------------


def test_a_chunk_without_choices_is_ignored():
    acc = Accumulator()
    assert acc.feed({"id": "x"}) == ""
    assert acc.content == ""


def test_a_chunk_with_empty_choices_is_ignored():
    assert Accumulator().feed({"id": "x", "choices": []}) == ""


def test_a_non_dict_choice_is_ignored():
    assert Accumulator().feed({"id": "x", "choices": ["oops"]}) == ""


def test_a_non_dict_delta_is_ignored():
    assert Accumulator().feed({"id": "x", "choices": [{"delta": "oops"}]}) == ""


def test_a_non_string_content_is_ignored():
    assert Accumulator().feed(_chunk(content=42)) == ""


# --- tool_calls --------------------------------------------------------------


def _call_fragment(index: int = 0, **function) -> dict:
    fragment: dict = {"index": index}
    if "call_id" in function:
        fragment["id"] = function.pop("call_id")
    fragment["function"] = function
    return fragment


def test_tool_call_arguments_are_joined_by_index():
    """§9 의 예시 그대로 — 조각난 arguments 는 합쳐져야 JSON 이 된다."""
    acc = Accumulator()
    acc.feed(
        _chunk(
            tool_calls=[_call_fragment(call_id="call_1", name="send_email", arguments='{"to":"aud')]
        )
    )
    acc.feed(_chunk(tool_calls=[_call_fragment(arguments="it@evil.co")]))
    acc.feed(_chunk(tool_calls=[_call_fragment(arguments='m"}')]))

    calls = acc.tool_calls
    assert len(calls) == 1
    assert calls[0]["function"]["arguments"] == '{"to":"audit@evil.com"}'
    assert orjson.loads(calls[0]["function"]["arguments"]) == {"to": "audit@evil.com"}


def test_tool_call_name_and_id_come_from_the_first_fragment():
    acc = Accumulator()
    acc.feed(
        _chunk(tool_calls=[_call_fragment(call_id="call_9", name="send_email", arguments="{}")])
    )
    acc.feed(_chunk(tool_calls=[_call_fragment(arguments="")]))

    call = acc.tool_calls[0]
    assert call["id"] == "call_9"
    assert call["function"]["name"] == "send_email"


def test_a_later_empty_name_does_not_overwrite():
    acc = Accumulator()
    acc.feed(_chunk(tool_calls=[_call_fragment(call_id="c", name="send_email", arguments="{")]))
    acc.feed(_chunk(tool_calls=[{"index": 0, "function": {"name": "", "arguments": "}"}}]))
    assert acc.tool_calls[0]["function"]["name"] == "send_email"


def test_two_tool_calls_accumulate_independently():
    acc = Accumulator()
    acc.feed(
        _chunk(tool_calls=[_call_fragment(0, call_id="a", name="read_file", arguments='{"p":')])
    )
    acc.feed(
        _chunk(tool_calls=[_call_fragment(1, call_id="b", name="send_email", arguments='{"to":')])
    )
    acc.feed(_chunk(tool_calls=[_call_fragment(0, arguments='"/x"}')]))
    acc.feed(_chunk(tool_calls=[_call_fragment(1, arguments='"e@x.com"}')]))

    calls = acc.tool_calls
    assert [c["function"]["name"] for c in calls] == ["read_file", "send_email"]
    assert calls[0]["function"]["arguments"] == '{"p":"/x"}'
    assert calls[1]["function"]["arguments"] == '{"to":"e@x.com"}'


def test_calls_are_ordered_by_index():
    acc = Accumulator()
    acc.feed(_chunk(tool_calls=[_call_fragment(1, call_id="b", name="second", arguments="{}")]))
    acc.feed(_chunk(tool_calls=[_call_fragment(0, call_id="a", name="first", arguments="{}")]))
    assert [c["function"]["name"] for c in acc.tool_calls] == ["first", "second"]


def test_a_malformed_tool_call_fragment_is_ignored():
    acc = Accumulator()
    acc.feed(_chunk(tool_calls="oops"))
    acc.feed(_chunk(tool_calls=["oops"]))
    acc.feed(_chunk(tool_calls=[{"index": "no", "function": {"arguments": "x"}}]))
    assert acc.tool_calls == []


def test_has_tool_calls():
    acc = Accumulator()
    assert acc.has_tool_calls is False
    acc.feed(_chunk(tool_calls=[_call_fragment(call_id="a", name="x", arguments="{}")]))
    assert acc.has_tool_calls is True


# --- ④ 검사기와 같은 형태 ---------------------------------------------------


def test_the_accumulated_shape_matches_what_the_inspector_reads():
    """검사기가 SSE 를 모르게 하려면 여기서 형태를 맞춰야 한다."""
    acc = Accumulator()
    acc.feed(_chunk(role="assistant"))
    acc.feed(
        _chunk(
            tool_calls=[
                _call_fragment(call_id="call_1", name="send_email", arguments='{"to":"e@x.com"}')
            ]
        )
    )
    acc.feed(_finish("tool_calls"))

    body = acc.as_completion()
    found = extract_tool_calls(body)
    assert len(found) == 1
    assert tool_name(found[0]) == "send_email"
    assert dict(argument_strings(found[0]))["to"] == "e@x.com"


def test_as_completion_carries_the_content():
    acc = Accumulator()
    acc.feed(_chunk(content="hello"))
    acc.feed(_finish("stop"))
    body = acc.as_completion(content=acc.content)
    assert body["choices"][0]["message"]["content"] == "hello"
    assert body["choices"][0]["finish_reason"] == "stop"


def test_as_completion_omits_tool_calls_when_there_are_none():
    acc = Accumulator()
    acc.feed(_chunk(content="hi"))
    assert "tool_calls" not in acc.as_completion(content="hi")["choices"][0]["message"]


def test_as_completion_keeps_the_template_fields():
    acc = Accumulator()
    acc.feed(_chunk(content="hi"))
    body = acc.as_completion(content="hi")
    assert body["id"] == "cmpl-1"
    assert body["model"] == "gpt-4o"
