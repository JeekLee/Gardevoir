"""Holdback emitter with an overlapping inspection window (§9).

**항상 마지막 N자를 손에 쥔다.** 위험 패턴이 완성되는 순간 그 부분은 아직 방출 전이므로
치환하고 계속 흘릴 수 있다 — 사용자가 아직 안 봤으니 "사후 수정"이 아니라 그게 원본이다.

```
모델 생성   "고객 주민번호는 900101-1234567 입니다"
                            └────────────────┘  홀드백 창 안에서 완성
방출        "고객 주민번호는 [개인정보 삭제됨] 입니다"    ← 치환하고 계속
```

**겹치는 윈도우**로 청크 경계에 걸친 매치를 잡는다. 누적 전체를 매 청크마다 스캔하면
O(n²) 이므로 최근 구간만 본다.

```
생성:   "주민번호는 900101-"  "1234567 입니다"
청크별 검사:  A 에 패턴 없음. B 에 패턴 없음. → 놓침
윈도우 검사:  직전 K자 + 새 청크 → 잡음
```
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class Holdback:
    """방출을 늦추고, 아직 방출 안 된 구간은 고칠 수 있게 한다.

    ``chars`` 가 0 이면 즉시 방출이다 — §9 의 Post 패턴. 그때는 마스킹이 성립하지
    않는다(이미 나간 것을 되돌릴 수 없다). 호출자가 그 사실을 보고해야 한다.
    """

    chars: int
    window: int
    #: 지금까지 도착한 전체 텍스트. 마스킹이 이 위에서 일어난다.
    buffer: str = ""
    #: 이미 방출한 길이. 이 앞은 고칠 수 없다.
    emitted: int = 0
    #: 마지막으로 검사한 위치 — 윈도우 시작을 여기서 뒤로 잡는다.
    _inspected: int = field(default=0, repr=False)

    def offer(self, piece: str) -> str:
        """새 조각을 받고 **지금 방출할 부분**을 돌려준다."""
        self.buffer += piece
        return self._release()

    def flush(self) -> str:
        """스트림이 끝났다. 붙들고 있던 것을 전부 내보낸다."""
        released = self.buffer[self.emitted :]
        self.emitted = len(self.buffer)
        return released

    def inspection_window(self) -> tuple[str, int]:
        """``(검사할 텍스트, 그 시작 오프셋)``.

        직전 ``window`` 자를 겹쳐서 본다. 새로 온 것만 보면 경계에 걸친 매치를 놓친다.
        """
        start = max(0, self._inspected - self.window)
        self._inspected = len(self.buffer)
        return self.buffer[start:], start

    def mask(self, start: int, end: int, placeholder: str) -> bool:
        """``[start, end)`` 를 치환한다. 이미 방출된 구간이면 ``False``.

        방출된 구간을 고쳐도 사용자가 본 것은 지워지지 않는다. 거짓으로 "가렸다"고
        보고하지 않는 것이 중요하다 — 그것이 조용한 fail-open 이다.
        """
        if start < self.emitted:
            return False
        if not 0 <= start < end <= len(self.buffer):
            return False
        self.buffer = self.buffer[:start] + placeholder + self.buffer[end:]
        # 치환으로 길이가 바뀌었으니 검사 위치를 되돌려 다음 윈도우가 겹치게 한다.
        self._inspected = min(self._inspected, start + len(placeholder))
        return True

    @property
    def unemitted(self) -> str:
        return self.buffer[self.emitted :]

    def _release(self) -> str:
        keep = len(self.buffer) - self.chars
        if keep <= self.emitted:
            return ""
        released = self.buffer[self.emitted : keep]
        self.emitted = keep
        return released


__all__ = ["Holdback"]
