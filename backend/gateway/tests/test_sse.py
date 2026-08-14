"""SSE 코덱.

이해하지 못한 프레임을 그대로 중계하는 것이 이 모듈의 핵심 성질이다 — 파서 때문에
응답을 잃으면 가드레일이 가용성 문제가 된다.
"""

import orjson

from gateway.application.streaming.sse import (
    Frame,
    parse_frames,
    render,
    render_done,
)


def _data(payload: dict) -> bytes:
    return b"data: " + orjson.dumps(payload) + b"\n\n"


# --- 파싱 --------------------------------------------------------------------


def test_one_frame():
    frames, tail = parse_frames(_data({"id": "a"}))
    assert [f.payload for f in frames] == [{"id": "a"}]
    assert tail == b""


def test_many_frames_in_one_read():
    frames, tail = parse_frames(_data({"n": 1}) + _data({"n": 2}) + _data({"n": 3}))
    assert [f.payload["n"] for f in frames] == [1, 2, 3]
    assert tail == b""


def test_a_frame_split_across_reads_is_buffered():
    """TCP 는 프레임 경계를 지켜주지 않는다."""
    whole = _data({"id": "split"})
    first, second = whole[:12], whole[12:]

    frames, tail = parse_frames(first)
    assert frames == []
    assert tail == first

    frames, tail = parse_frames(tail + second)
    assert [f.payload for f in frames] == [{"id": "split"}]
    assert tail == b""


def test_the_tail_is_returned_for_the_next_read():
    frames, tail = parse_frames(_data({"n": 1}) + b'data: {"n": 2')
    assert len(frames) == 1
    assert tail == b'data: {"n": 2'


def test_the_done_sentinel_is_recognised():
    frames, _ = parse_frames(b"data: [DONE]\n\n")
    assert frames[0].is_done is True
    assert frames[0].payload is None
    assert frames[0].is_data is False


def test_done_after_a_data_frame():
    frames, _ = parse_frames(_data({"n": 1}) + b"data: [DONE]\n\n")
    assert [f.is_done for f in frames] == [False, True]


def test_a_non_json_frame_is_kept_verbatim():
    """이해 못한 프레임도 중계해야 한다."""
    frames, _ = parse_frames(b"data: not json at all\n\n")
    assert frames[0].payload is None
    assert frames[0].raw == b"data: not json at all\n\n"


def test_a_json_scalar_frame_is_kept_verbatim():
    """dict 가 아니면 우리가 해석할 것이 없다."""
    frames, _ = parse_frames(b"data: 42\n\n")
    assert frames[0].payload is None


def test_a_comment_frame_is_kept():
    """`: keep-alive` 는 구현체가 연결 유지에 쓴다."""
    frames, _ = parse_frames(b": keep-alive\n\n")
    assert frames[0].payload is None
    assert frames[0].raw == b": keep-alive\n\n"


def test_an_event_field_is_kept():
    frames, _ = parse_frames(b"event: ping\n\n")
    assert frames[0].payload is None


def test_crlf_line_endings():
    """구현체마다 다르다."""
    frames, tail = parse_frames(b"data: " + orjson.dumps({"n": 1}) + b"\r\n\r\n")
    assert [f.payload["n"] for f in frames] == [1]
    assert tail == b""


def test_an_empty_read_yields_nothing():
    assert parse_frames(b"") == ([], b"")


def test_blank_frames_are_skipped():
    frames, _ = parse_frames(b"\n\n" + _data({"n": 1}) + b"\n\n")
    assert len(frames) == 1


def test_a_frame_without_a_space_after_data():
    """스펙은 공백을 선택으로 둔다."""
    frames, _ = parse_frames(b"data:" + orjson.dumps({"n": 1}) + b"\n\n")
    assert frames[0].payload["n"] == 1


# --- 직렬화 ------------------------------------------------------------------


def test_render_round_trips():
    frames, tail = parse_frames(render({"id": "x", "choices": []}))
    assert frames[0].payload == {"id": "x", "choices": []}
    assert tail == b""


def test_render_done_round_trips():
    frames, _ = parse_frames(render_done())
    assert frames[0].is_done is True


def test_render_produces_one_frame():
    assert render({"a": 1}).count(b"\n\n") == 1


def test_a_rendered_frame_starts_with_data():
    assert render({"a": 1}).startswith(b"data: ")


# --- Frame ------------------------------------------------------------------


def test_a_data_frame_reports_itself():
    assert Frame(raw=b"", payload={"a": 1}).is_data is True
    assert Frame(raw=b"").is_data is False
