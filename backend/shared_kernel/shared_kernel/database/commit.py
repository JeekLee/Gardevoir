"""When a write becomes durable.

FastAPI 는 ``yield`` 의존성의 정리 코드를 응답을 보낸 뒤에 돌린다. 커밋을 조립 루트에 맡기면
발행이 200 을 돌려준 직후의 요청이 **이전 계획** 을 보고, draft 를 고친 뒤 곧바로 발행하면
**이전 draft** 를 읽는다 — 둘 다 실측이다. 그래서 서비스가 시점을 정한다.

여는 것은 SQLAlchemy 가 첫 SQL 에서(autobegin), 되돌리는 것은 ``async with`` 를 나가며
``close()`` 가 한다. 둘은 응답보다 앞일 필요가 없어서 여기 없다.
"""

from collections.abc import Awaitable, Callable

#: ``session.commit`` 을 그대로 넘긴다 — 세션 타입은 application 계층이 몰라야 한다.
Commit = Callable[[], Awaitable[None]]

__all__ = ["Commit"]
