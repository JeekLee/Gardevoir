"""SSE frame codec.

**이해하지 못한 프레임은 그대로 중계한다.** 프록시가 SSE 파서 때문에 응답을 잃으면
가드레일이 가용성 문제가 된다 — 업스트림 구현체마다 CRLF·주석 프레임·청크 경계가 다르다.
"""

from dataclasses import dataclass

import orjson

DATA_PREFIX = b"data:"
DONE_PAYLOAD = b"[DONE]"
FRAME_SEPARATOR = b"\n\n"


@dataclass(frozen=True, slots=True)
class Frame:
    """SSE 프레임 하나.

    ``payload`` 가 ``None`` 이면 우리가 이해하지 못한 프레임이다 — ``raw`` 를 그대로
    내보내야 한다.
    """

    raw: bytes
    payload: dict | None = None
    is_done: bool = False

    @property
    def is_data(self) -> bool:
        return self.payload is not None


def parse_frames(buffer: bytes) -> tuple[list[Frame], bytes]:
    """``(완성된 프레임들, 남은 꼬리)``.

    TCP 는 프레임 경계를 지켜주지 않는다. 꼬리를 돌려주고 다음 읽기에 이어 붙인다.
    """
    frames: list[Frame] = []
    # CRLF 를 LF 로 정규화한다 — 구분자 판정이 구현체에 따라 갈리지 않게.
    normalised = buffer.replace(b"\r\n", b"\n")
    while True:
        index = normalised.find(FRAME_SEPARATOR)
        if index < 0:
            return frames, normalised
        block, normalised = normalised[:index], normalised[index + len(FRAME_SEPARATOR) :]
        if block.strip():
            frames.append(_frame(block))


def render(payload: dict) -> bytes:
    return DATA_PREFIX + b" " + orjson.dumps(payload) + FRAME_SEPARATOR


def render_done() -> bytes:
    return DATA_PREFIX + b" " + DONE_PAYLOAD + FRAME_SEPARATOR


def _frame(block: bytes) -> Frame:
    raw = block + FRAME_SEPARATOR
    if not block.startswith(DATA_PREFIX):
        # 주석(`: keep-alive`)이나 다른 필드. 그대로 흘린다.
        return Frame(raw=raw)

    data = block[len(DATA_PREFIX) :].strip()
    if data == DONE_PAYLOAD:
        return Frame(raw=raw, is_done=True)
    try:
        payload = orjson.loads(data)
    except orjson.JSONDecodeError:
        return Frame(raw=raw)
    if not isinstance(payload, dict):
        return Frame(raw=raw)
    return Frame(raw=raw, payload=payload)


__all__ = [
    "DATA_PREFIX",
    "DONE_PAYLOAD",
    "FRAME_SEPARATOR",
    "Frame",
    "parse_frames",
    "render",
    "render_done",
]
