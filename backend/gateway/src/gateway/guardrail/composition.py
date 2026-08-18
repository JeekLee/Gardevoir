"""Guardrail 의 요청 수명 배선.

조립 루트는 ``app.py`` 다 — identity/composition.py 의 설명과 같다.
"""

from collections.abc import AsyncIterator

from fastapi import Request

from gateway.guardrail.definition.application.service.guardrail_service import GuardrailService
from gateway.guardrail.definition.infrastructure.guardrail_dao import SqlAlchemyGuardrailDao
from gateway.guardrail.definition.infrastructure.guardrail_repository import (
    SqlAlchemyGuardrailRepository,
)


async def provide_guardrail_service(request: Request) -> AsyncIterator[GuardrailService]:
    """One session per request. 커밋은 서비스가 한다 — shared_kernel.database.transaction 참조."""
    async with request.app.state.session_factory() as session:
        yield GuardrailService(
            guardrails=SqlAlchemyGuardrailRepository(session),
            dao=SqlAlchemyGuardrailDao(session),
            commit=session.commit,
            # 기본값을 두지 않는다. 레지스트리는 lifespan 이 항상 만들고, 없는데도
            # None 으로 넘어가면 발행이 재컴파일 없이 200 을 돌려준다 — 배선 실수가
            # 예외 대신 조용한 무동작이 된다.
            plans=request.app.state.plans,
        )
