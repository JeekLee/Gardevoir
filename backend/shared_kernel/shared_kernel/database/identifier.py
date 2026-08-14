"""UUIDv7 — 시간순으로 정렬되는 식별자 (RFC 9562).

가변 상태의 PK 에 쓴다. v4 는 완전 랜덤이라 인덱스 삽입이 흩어지는데, v7 은 앞 48비트가
밀리초 타임스탬프라 시간순으로 쌓인다.

**표준 라이브러리에 없다.** ``uuid.uuid7()`` 은 Python 3.14 에 들어갔고 우리는 3.12 다.
15줄이면 되는 것에 네이티브 확장 의존성(``uuid-utils``)을 더할 이유가 없다.

같은 밀리초 안에서의 단조 증가는 보장하지 않는다 — RFC 가 선택으로 두고 있고, 우리는
정렬 순서에 의미를 부여하지 않는다(감사 로그의 시간순은 ULID 와 ``created_at`` 이 맡는다).
"""

import secrets
import time
from uuid import UUID

_MS_MASK = 0xFFFFFFFFFFFF
_RAND_A_BITS = 12
_RAND_B_BITS = 62


def uuid7() -> UUID:
    """``unix_ts_ms(48) | ver(4) | rand_a(12) | var(2) | rand_b(62)``."""
    timestamp_ms = int(time.time() * 1000) & _MS_MASK
    random_bits = secrets.randbits(_RAND_A_BITS + _RAND_B_BITS)
    rand_a = random_bits >> _RAND_B_BITS
    rand_b = random_bits & ((1 << _RAND_B_BITS) - 1)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)  # version
        | (rand_a << 64)
        | (0b10 << 62)  # variant
        | rand_b
    )
    return UUID(int=value)


__all__ = ["uuid7"]
