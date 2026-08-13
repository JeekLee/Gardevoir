"""Unit-of-work boundary.

발행은 커밋 **뒤에** 재컴파일해야 하고(새 세션이 미커밋 행을 못 본다), 그것이
**응답 전에** 끝나야 한다. FastAPI 는 yield 의존성의 정리 코드를 응답을 보낸 뒤에
돌리므로, 조립 루트에 커밋을 맡기면 발행이 200 을 돌려준 직후의 요청이 이전 계획을
본다 — 실측으로 확인했다.

그래서 서비스가 커밋 시점을 알아야 한다. 세션 타입은 몰라야 하므로 포트로 둔다.
"""

from typing import Protocol


class Transaction(Protocol):
    async def commit(self) -> None: ...
