"""Session-per-operation adapter over the SQLAlchemy repository.

프로세스 수명 동안 살아 있는 캐시 뒤에 놓이므로, 대부분의 요청은 여기까지 오지
않는다 (§6). 요청 경로에 DB 접근이 없어야 한다는 제약을 캐시가 지키고, 이 어댑터는
캐시가 비었을 때만 세션을 연다.

조립 루트(app.py)에 두지 않는다. 어댑터를 배선 파일에 정의하면 레이어링 테스트의
면제 목록 뒤에 숨어서, 인프라 구현체가 presentation 층에 사는 것을 아무도 못 본다.
같은 패턴의 guardrail 쪽(SessionScopedGuardrailSource)은 처음부터 infrastructure 에
있었다.
"""

from collections.abc import Callable

from gateway.identity.domain.models.api_key import ApiKey
from gateway.identity.infrastructure.api_key_repository import SqlAlchemyApiKeyRepository


class SessionScopedApiKeyRepository:
    """Opens a short-lived session per operation."""

    def __init__(self, session_factory: Callable) -> None:
        self._session_factory = session_factory

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        async with self._session_factory() as session:
            return await SqlAlchemyApiKeyRepository(session).find_by_hash(key_hash)

    async def add(self, key: ApiKey) -> None:
        async with self._session_factory() as session:
            await SqlAlchemyApiKeyRepository(session).add(key)
            await session.commit()
