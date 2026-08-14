"""Guardrail 의 요청 수명 배선.

조립 루트는 ``app.py`` 다 — identity/composition.py 의 설명과 같다.
"""

from collections.abc import AsyncIterator

from fastapi import Request

from gateway.guardrail.definition.application.guardrail_service import GuardrailService
from gateway.guardrail.definition.infrastructure.guardrail_dao import SqlAlchemyGuardrailDao
from gateway.guardrail.definition.infrastructure.guardrail_repository import (
    SqlAlchemyGuardrailRepository,
)


async def provide_guardrail_service(request: Request) -> AsyncIterator[GuardrailService]:
    """One session per request, committed only on the success path."""
    async with request.app.state.session_factory() as session:
        yield GuardrailService(
            guardrails=SqlAlchemyGuardrailRepository(session),
            dao=SqlAlchemyGuardrailDao(session),
            # 발행은 커밋과 재컴파일 시점을 스스로 알아야 한다 — 정리 코드에 맡기면
            # FastAPI 가 응답을 보낸 뒤에 돌려서 발행 직후의 요청이 이전 계획을 본다.
            # definition/application/transaction.py 참조.
            transaction=session,
            # 기본값을 두지 않는다. 레지스트리는 lifespan 이 항상 만들고, 없는데도
            # None 으로 넘어가면 발행이 재컴파일 없이 200 을 돌려준다 — 배선 실수가
            # 예외 대신 조용한 무동작이 된다.
            plans=request.app.state.plans,
        )
        # 서비스가 자기 쓰기를 이미 커밋했다. 여기서는 남은 것을 정리한다 —
        # 읽기 전용 라우트의 트랜잭션을 닫고, 실패한 요청은 async with 가 롤백한다.
        await session.commit()
