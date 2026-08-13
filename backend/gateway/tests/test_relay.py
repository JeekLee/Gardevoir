"""스트리밍 중계 — §9 의 두 장치가 실제로 도는지.

핵심: 청크 경계에 걸친 패턴을 잡고, 홀드백 안이면 멈추지 않고 치환한다.
"""

import orjson
import pytest

from gateway.application.inspection.inspector import Inspector
from gateway.application.inspection.outcome import MASK_PLACEHOLDER
from gateway.application.plan.compiler import compile_guardrail
from gateway.application.streaming.relay import STOP_NOTICE, StreamRelay
from gateway.application.streaming.sse import parse_frames
from gateway.contract import FINISH_CONTENT_FILTER, Mode
from gateway.domain.models.guardrail import Edge, Guardrail, Node, NodeType

RRN = r"\d{6}-\d{7}"


class StubRegistry:
    def __init__(self, plan=None):
        self._plan = plan

    def get(self, name):
        return self._plan


def _plan(checkpoint: str = "output", *, pattern: str = RRN, action: str = "block"):
    guardrail = Guardrail(
        name="g",
        version="1",
        version_number=1,
        nodes=(
            Node(id="e", type=NodeType.EXTRACT, config={"checkpoint": checkpoint}),
            Node(id="r", type=NodeType.REGEX, config={"pattern": pattern}),
            Node(
                id="v",
                type=NodeType.VERDICT,
                config={"decision": "conclusive", "action": action},
            ),
        ),
        edges=(Edge("e", "r"), Edge("r", "v")),
    )
    guardrail.validate()
    return compile_guardrail(guardrail)


def _tool_plan(read_only=("read_file",)):
    guardrail = Guardrail(
        name="g",
        version="1",
        version_number=1,
        nodes=(
            Node(id="t", type=NodeType.TAINT, config={"checkpoint": "tool_call"}),
            Node(
                id="s",
                type=NodeType.SIDE_EFFECT,
                config={"checkpoint": "tool_call", "read_only": list(read_only)},
            ),
            Node(id="a", type=NodeType.ALL, config={}),
            Node(
                id="v",
                type=NodeType.VERDICT,
                config={"decision": "conclusive", "action": "block"},
            ),
        ),
        edges=(Edge("t", "a"), Edge("s", "a"), Edge("a", "v")),
    )
    guardrail.validate()
    return compile_guardrail(guardrail)


def _chunk(**delta) -> bytes:
    return (
        b"data: "
        + orjson.dumps(
            {
                "id": "cmpl-1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-4o",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
        )
        + b"\n\n"
    )


def _finish(reason: str = "stop") -> bytes:
    return (
        b"data: "
        + orjson.dumps(
            {
                "id": "cmpl-1",
                "model": "gpt-4o",
                "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
            }
        )
        + b"\n\n"
    )


async def _upstream(*raws: bytes):
    for raw in raws:
        yield raw


async def _run(relay: StreamRelay, *raws: bytes) -> tuple[str, list[dict]]:
    out = b""
    async for chunk in relay.relay(_upstream(*raws)):
        out += chunk
    frames, _ = parse_frames(out)
    payloads = [f.payload for f in frames if f.payload is not None]
    text = "".join(
        p["choices"][0]["delta"].get("content", "")
        for p in payloads
        if p.get("choices") and isinstance(p["choices"][0].get("delta"), dict)
    )
    return text, payloads


def _relay(plan=None, *, holdback=64, window=32, tainted=False, payload=None, mode=Mode.ENFORCE):
    return StreamRelay(
        inspector=Inspector(plans=StubRegistry(plan)),
        plan=plan,
        mode=mode,
        tainted=tainted,
        payload=payload or {"messages": []},
        holdback_chars=holdback,
        window_chars=window,
    )


# --- 통과 --------------------------------------------------------------------


async def test_a_clean_stream_is_relayed():
    text, payloads = await _run(
        _relay(_plan()),
        _chunk(role="assistant", content=""),
        _chunk(content="안녕하세요 "),
        _chunk(content="반갑습니다"),
        _finish(),
    )
    assert text == "안녕하세요 반갑습니다"
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"


async def test_a_stream_without_a_plan_is_relayed():
    text, _ = await _run(_relay(None), _chunk(content="hello"), _finish())
    assert text == "hello"


async def test_an_unknown_frame_is_relayed_verbatim():
    out = b""
    async for chunk in _relay(_plan()).relay(
        _upstream(b": keep-alive\n\n", _chunk(content="hi"), _finish())
    ):
        out += chunk
    assert b": keep-alive" in out


# --- §9 의 핵심 문제 --------------------------------------------------------


async def test_a_pattern_spanning_two_chunks_is_caught():
    """청크별로 보면 A 에도 B 에도 패턴이 없다 — 겹치는 윈도우가 필요하다."""
    relay = _relay(_plan(), holdback=64)
    text, payloads = await _run(
        relay,
        _chunk(role="assistant"),
        _chunk(content="주민번호는 900101-"),
        _chunk(content="1234567 입니다"),
        _finish(),
    )
    assert relay.outcome.output.blocked is True
    assert payloads[-1]["choices"][0]["finish_reason"] == FINISH_CONTENT_FILTER
    assert "900101-1234567" not in text


async def test_the_block_appends_a_reason():
    """많은 앱이 finish_reason 을 보지 않는다 (§7.3)."""
    text, _ = await _run(
        _relay(_plan(), holdback=64),
        _chunk(content="번호 900101-1234567"),
        _finish(),
    )
    assert STOP_NOTICE in text


async def test_the_block_uses_a_standard_finish_reason():
    from gateway.contract import STANDARD_FINISH_REASONS

    _, payloads = await _run(
        _relay(_plan(), holdback=64), _chunk(content="900101-1234567"), _finish()
    )
    assert payloads[-1]["choices"][0]["finish_reason"] in STANDARD_FINISH_REASONS


async def test_the_stream_stops_after_a_block():
    """차단 뒤에 업스트림 내용이 더 나가면 안 된다."""
    text, _ = await _run(
        _relay(_plan(), holdback=64),
        _chunk(content="900101-1234567"),
        _chunk(content="그리고 더 많은 비밀"),
        _finish(),
    )
    assert "더 많은 비밀" not in text


# --- 마스킹 (홀드백 안) ------------------------------------------------------


async def test_masking_inside_the_holdback_does_not_stop_the_stream():
    """§9: 사용자가 아직 안 봤으니 치환이 사후 수정이 아니다."""
    relay = _relay(_plan(action="mask"), holdback=64)
    text, payloads = await _run(
        relay,
        _chunk(role="assistant"),
        _chunk(content="번호는 900101-"),
        _chunk(content="1234567 입니다"),
        _finish(),
    )
    assert relay.outcome.stopped is False
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    assert "900101-1234567" not in text
    assert MASK_PLACEHOLDER in text
    assert text == f"번호는 {MASK_PLACEHOLDER} 입니다"


async def test_zero_holdback_still_masks_within_one_chunk():
    """검사가 방출보다 앞서므로, 한 청크 안에서 완성된 패턴은 홀드백 0 에서도 가려진다.

    §9 가 홀드백 0 을 "사후 검출"이라 부른 것보다 조금 낫다 — 청크 단위로는 Pre 다.
    """
    relay = _relay(_plan(action="mask"), holdback=0)
    text, _ = await _run(relay, _chunk(content="번호는 900101-1234567 입니다"), _finish())
    assert relay.outcome.unmaskable == 0
    assert "900101-1234567" not in text
    assert MASK_PLACEHOLDER in text


async def test_zero_holdback_cannot_mask_across_chunks_and_says_so():
    """§9 의 Post 패턴 — 앞 청크가 이미 나갔으면 되돌릴 수 없다."""
    relay = _relay(_plan(action="mask"), holdback=0)
    text, _ = await _run(
        relay,
        _chunk(content="번호는 900101-"),
        _chunk(content="1234567 입니다"),
        _finish(),
    )
    assert relay.outcome.unmaskable >= 1, "못 가렸다는 사실을 남기지 않았다"
    assert "900101-" in text, "이미 나간 것은 되돌릴 수 없다"


async def test_a_full_holdback_masks_across_chunks():
    """홀드백이 있으면 같은 상황에서 가려진다 — 그게 홀드백의 존재 이유다 (§9)."""
    relay = _relay(_plan(action="mask"), holdback=64)
    text, _ = await _run(
        relay,
        _chunk(content="번호는 900101-"),
        _chunk(content="1234567 입니다"),
        _finish(),
    )
    assert relay.outcome.unmaskable == 0
    assert "900101-1234567" not in text
    assert MASK_PLACEHOLDER in text


async def test_a_masked_stream_reports_masked():
    relay = _relay(_plan(action="mask"), holdback=64)
    await _run(relay, _chunk(content="900101-1234567"), _finish())
    assert relay.outcome.output.masked is True


# --- ④ tool_call -------------------------------------------------------------


def _tool_fragment(index: int = 0, **function) -> bytes:
    fragment: dict = {"index": index}
    if "call_id" in function:
        fragment["id"] = function.pop("call_id")
    fragment["function"] = function
    return _chunk(tool_calls=[fragment])


async def test_arguments_split_across_chunks_are_joined():
    """§9 의 예시 그대로."""
    relay = _relay(_tool_plan(), tainted=True)
    _, payloads = await _run(
        relay,
        _chunk(role="assistant"),
        _tool_fragment(call_id="c1", name="read_file", arguments='{"path":"/a'),
        _tool_fragment(arguments='.txt"}'),
        _finish("tool_calls"),
    )
    calls = [
        c
        for p in payloads
        for c in (p["choices"][0]["delta"].get("tool_calls") or [])
        if p.get("choices")
    ]
    assert calls[0]["function"]["arguments"] == '{"path":"/a.txt"}'


async def test_a_blocked_streamed_tool_call_emits_no_tool_calls():
    relay = _relay(_tool_plan(), tainted=True)
    out = b""
    async for chunk in relay.relay(
        _upstream(
            _chunk(role="assistant"),
            _tool_fragment(call_id="c1", name="send_email", arguments='{"to":"e@x.com"}'),
            _finish("tool_calls"),
        )
    ):
        out += chunk

    assert relay.outcome.tool_call.blocked is True
    assert b"tool_calls" not in out
    assert b"e@x.com" not in out
    assert FINISH_CONTENT_FILTER.encode() in out


async def test_an_allowed_streamed_tool_call_is_relayed():
    relay = _relay(_tool_plan(read_only=("read_file", "send_email")), tainted=True)
    out = b""
    async for chunk in relay.relay(
        _upstream(
            _chunk(role="assistant"),
            _tool_fragment(call_id="c1", name="send_email", arguments='{"to":"e@x.com"}'),
            _finish("tool_calls"),
        )
    ):
        out += chunk

    assert relay.outcome.tool_call.blocked is False
    assert b"e@x.com" in out


async def test_tool_calls_are_never_emitted_in_fragments():
    """앱은 조각으로 아무것도 할 수 없다 — 완성본 하나로 낸다 (§9)."""
    relay = _relay(_tool_plan(read_only=("send_email",)), tainted=True)
    _, payloads = await _run(
        relay,
        _tool_fragment(call_id="c1", name="send_email", arguments='{"to":'),
        _tool_fragment(arguments='"e@x.com"}'),
        _finish("tool_calls"),
    )
    with_calls = [p for p in payloads if p["choices"][0]["delta"].get("tool_calls")]
    assert len(with_calls) == 1


async def test_the_tool_call_checkpoint_is_reported_even_without_calls():
    relay = _relay(_tool_plan(), tainted=True)
    await _run(relay, _chunk(content="그냥 텍스트"), _finish())
    assert relay.outcome.tool_call.ran is True


# --- dry-run -----------------------------------------------------------------


async def test_dry_run_does_not_stop_the_stream():
    relay = _relay(_plan(), holdback=64, mode=Mode.DRY_RUN)
    text, payloads = await _run(relay, _chunk(content="900101-1234567"), _finish())
    assert relay.outcome.stopped is False
    assert "900101-1234567" in text
    assert relay.outcome.output.would_have is not None


async def test_dry_run_does_not_mask():
    relay = _relay(_plan(action="mask"), holdback=64, mode=Mode.DRY_RUN)
    text, _ = await _run(relay, _chunk(content="900101-1234567"), _finish())
    assert "900101-1234567" in text
    assert MASK_PLACEHOLDER not in text


# --- 계정 --------------------------------------------------------------------


async def test_the_relay_reports_which_checkpoints_it_inspects():
    assert _relay(_plan()).inspects_output is True
    assert _relay(_plan()).inspects_tool_calls is False
    assert _relay(_tool_plan()).inspects_tool_calls is True
    assert _relay(None).inspects_output is False


async def test_usage_and_model_are_captured():
    relay = _relay(_plan())
    await _run(
        relay,
        _chunk(content="hi"),
        b"data: "
        + orjson.dumps({"id": "x", "model": "gpt-4o", "choices": [], "usage": {"prompt_tokens": 5}})
        + b"\n\n",
        _finish(),
    )
    assert relay.outcome.model == "gpt-4o"
    assert relay.outcome.usage["prompt_tokens"] == 5


@pytest.mark.parametrize("holdback", [0, 8, 64, 1024])
async def test_every_holdback_size_relays_a_clean_stream(holdback):
    text, _ = await _run(
        _relay(_plan(), holdback=holdback),
        _chunk(content="아무 문제 없는 "),
        _chunk(content="응답입니다"),
        _finish(),
    )
    assert text == "아무 문제 없는 응답입니다"
