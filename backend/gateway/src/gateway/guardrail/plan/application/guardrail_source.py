"""Where the plan registry reads guardrails from.

리포지토리를 직접 쓰지 않는 이유: 리포지토리는 세션(요청 수명)을 잡고 있고
레지스트리는 프로세스 수명이다. 이 포트의 어댑터가 호출마다 짧은 세션을 연다 —
Phase 1c 의 ``SessionScopedApiKeyRepository`` 와 같은 패턴이다.

폴링에 쓰이므로 ``latest_versions`` 는 그래프를 읽지 않는다. 번호만 비교해서
바뀐 것만 다시 가져온다.
"""

from typing import Protocol

from gateway.guardrail.domain.guardrail import Guardrail


class GuardrailSource(Protocol):
    async def latest_versions(self) -> dict[str, int]:
        """발행본이 있는 가드레일의 ``이름 -> 최신 발행 번호``. draft 만 있으면 제외."""
        ...

    async def load_published(self, name: str, version_number: int) -> Guardrail | None: ...
