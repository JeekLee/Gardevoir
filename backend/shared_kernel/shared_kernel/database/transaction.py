"""Unit-of-work boundary.

커밋은 **응답이 나가기 전에** 끝나야 하므로 서비스가 시점을 소유한다. 조립 루트의
``yield`` 정리 코드에 맡기면 FastAPI 가 응답을 보낸 뒤에 커밋하고, 그러면 draft 를 고치고
곧바로 발행하는 요청이 **이전 draft** 를 읽고 발행 직후의 프록시 요청이 **이전 계획** 을
본다. 둘 다 실측으로 확인했다 — ASGITransport 는 전체 ASGI 호출을 기다려주므로 테스트로는
이 차이가 보이지 않는다.

세션 타입은 몰라야 하므로 포트로 둔다. 세션을 여는 ``get_session_factory`` 가 여기 있으니
그 경계도 여기 있다.

메서드가 ``commit`` 하나인 것은 의도다. 여는 것은 ``async with session_factory()`` 가, 되돌리는
것은 그 블록을 나가는 것이 한다. ``rollback`` 을 여기 더하면 서비스가 되돌린 뒤 정상 반환해서
**아무것도 저장되지 않은 200** 을 만들 수 있다. 이 포트가 고르는 것은 시점 하나다.
"""

from typing import Protocol


class Transaction(Protocol):
    async def commit(self) -> None: ...


__all__ = ["Transaction"]
