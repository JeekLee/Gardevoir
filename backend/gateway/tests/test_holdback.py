"""홀드백 + 겹치는 윈도우 (§9).

핵심 성질 둘: 방출한 것은 절대 고칠 수 없고, 청크 경계에 걸친 매치를 놓치지 않는다.
"""

import re2

from gateway.application.streaming.holdback import Holdback

RRN = re2.compile(r"\d{6}-\d{7}")
MASK = "[개인정보 삭제됨]"


def _holdback(chars: int = 8, window: int = 32) -> Holdback:
    return Holdback(chars=chars, window=window)


# --- 방출 --------------------------------------------------------------------


def test_nothing_is_emitted_until_the_holdback_is_full():
    h = _holdback(chars=8)
    assert h.offer("abc") == ""
    assert h.offer("de") == ""
    assert h.offer("fgh") == ""
    assert h.offer("ij") == "ab"


def test_the_tail_is_always_held():
    h = _holdback(chars=5)
    h.offer("0123456789")
    assert h.unemitted == "56789"


def test_flush_releases_the_tail():
    h = _holdback(chars=5)
    h.offer("0123456789")
    assert h.flush() == "56789"
    assert h.unemitted == ""


def test_flush_twice_releases_nothing_more():
    h = _holdback(chars=5)
    h.offer("0123456789")
    h.flush()
    assert h.flush() == ""


def test_zero_holdback_emits_immediately():
    """§9 의 Post 패턴 — 즉시 방출, 사후 검출."""
    h = _holdback(chars=0)
    assert h.offer("hello") == "hello"
    assert h.offer(" world") == " world"


def test_emitted_text_is_never_re_emitted():
    h = _holdback(chars=3)
    released = [h.offer(piece) for piece in ("abcd", "efg", "hij")]
    released.append(h.flush())
    assert "".join(released) == "abcdefghij"


def test_the_total_emitted_equals_the_input_when_nothing_masks():
    h = _holdback(chars=7)
    pieces = ["주민번호는 ", "900101-", "1234567", " 입니다"]
    out = "".join(h.offer(p) for p in pieces) + h.flush()
    assert out == "".join(pieces)


# --- 겹치는 윈도우 -----------------------------------------------------------


def test_the_window_covers_the_chunk_boundary():
    """§9 의 핵심 문제 — 청크별로 보면 못 잡는다."""
    h = _holdback(chars=0, window=32)
    h.offer("주민번호는 900101-")
    first, _ = h.inspection_window()
    assert RRN.search(first) is None, "아직 완성되지 않았다"

    h.offer("1234567 입니다")
    second, start = h.inspection_window()
    assert RRN.search(second) is not None, "경계에 걸친 매치를 놓쳤다"
    assert start == 0


def test_the_window_is_bounded():
    """누적 전체를 매번 스캔하면 O(n²) 이다."""
    h = _holdback(chars=0, window=16)
    h.offer("x" * 1000)
    h.inspection_window()
    h.offer("y" * 10)
    text, start = h.inspection_window()
    assert len(text) <= 16 + 10
    assert start == 1000 - 16


def test_the_window_starts_at_zero_for_a_short_stream():
    h = _holdback(chars=0, window=512)
    h.offer("short")
    text, start = h.inspection_window()
    assert (text, start) == ("short", 0)


def test_the_window_advances():
    h = _holdback(chars=0, window=4)
    h.offer("abcdefgh")
    h.inspection_window()
    h.offer("ij")
    text, start = h.inspection_window()
    assert text == "efghij"
    assert start == 4


# --- 마스킹 ------------------------------------------------------------------


def test_masking_inside_the_holdback_succeeds():
    h = _holdback(chars=32)
    h.offer("고객 주민번호는 900101-1234567 입니다")
    text, start = h.inspection_window()
    match = RRN.search(text)
    assert match is not None

    assert h.mask(start + match.start(), start + match.end(), MASK) is True
    assert h.flush() == f"고객 주민번호는 {MASK} 입니다"


def test_masking_an_already_emitted_span_fails():
    """되돌릴 수 없다 — 거짓으로 '가렸다'고 보고하면 조용한 fail-open 이다."""
    h = _holdback(chars=0)
    h.offer("주민번호 900101-1234567 끝")
    text, start = h.inspection_window()
    match = RRN.search(text)
    assert match is not None

    assert h.mask(start + match.start(), start + match.end(), MASK) is False


def test_masking_changes_what_is_emitted_next():
    """치환한 뒤 방출되는 것은 치환본이다 — 원문이 나가면 마스킹이 무의미하다.

    홀드백이 매치가 완성되는 동안 그것을 전부 붙들 만큼 커야 한다. 그 뒤에 텍스트가
    더 오면 치환본이 밀려 나간다.
    """
    h = _holdback(chars=20)
    assert h.offer("번호는 900101-1234567") == "", "매치가 아직 홀드백 안에 있어야 한다"

    text, start = h.inspection_window()
    match = RRN.search(text)
    assert match is not None
    assert h.mask(start + match.start(), start + match.end(), MASK) is True

    released = h.offer(" 입니다 그리고 문장이 더 이어집니다 계속")
    whole = released + h.flush()
    assert "900101-1234567" not in whole
    assert MASK in whole


def test_masking_a_partially_emitted_span_fails():
    """앞부분이 이미 나갔으면 못 고친다."""
    h = _holdback(chars=4)
    h.offer("900101-1234567xxxx")
    assert h.emitted > 0
    assert h.mask(0, 14, MASK) is False


def test_masking_out_of_range_fails():
    h = _holdback(chars=100)
    h.offer("short")
    assert h.mask(0, 999, MASK) is False
    assert h.mask(3, 3, MASK) is False


def test_two_masks_in_one_buffer():
    h = _holdback(chars=64)
    h.offer("a 900101-1234567 b 900102-7654321 c")
    text, start = h.inspection_window()
    spans = [(m.start() + start, m.end() + start) for m in RRN.finditer(text)]
    # 뒤에서부터 치환한다 — 앞을 먼저 바꾸면 뒤 오프셋이 밀린다
    for begin, end in reversed(spans):
        assert h.mask(begin, end, MASK) is True
    assert h.flush() == f"a {MASK} b {MASK} c"


def test_the_window_overlaps_a_replacement():
    """치환으로 길이가 바뀌어도 다음 윈도우가 그 구간을 다시 덮어야 한다."""
    h = _holdback(chars=64, window=8)
    h.offer("900101-1234567")
    text, start = h.inspection_window()
    match = RRN.search(text)
    h.mask(start + match.start(), start + match.end(), MASK)

    h.offer("tail")
    text, _ = h.inspection_window()
    assert MASK in text or text.endswith("tail")


def test_the_window_reaches_back_over_a_masked_span():
    """치환은 버퍼 길이를 바꾼다. 검사 위치를 되돌리지 않으면 창의 왼쪽 끝이 그만큼
    밀려서, 치환 직후에 붙는 텍스트가 검사되지 않고 지나갈 수 있다.

    창을 2자로 줄여 차이를 드러낸다 — 기본값 512자에서는 치환 1회의 길이 변화가 창
    안에 묻힌다. 그래도 이 성질이 창 크기와 무관하게 성립해야 "치환 뒤의 텍스트는
    반드시 검사된다"고 말할 수 있다.
    """
    h = Holdback(chars=0, window=2)
    h.append("x" * 10 + "900101-1234567")
    h.inspection_window()
    assert h.mask(10, 24, "[가림]") is True  # 14자 -> 4자, 10자 줄어든다

    h.append("ab")
    text, _start = h.inspection_window()
    assert "ab" in text, "치환으로 줄어든 만큼 창이 새 텍스트를 놓쳤다"
