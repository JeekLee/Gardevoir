"""GuardrailSource over a session factory.

호출마다 짧은 세션을 연다. 요청 경로가 아니다 — 기동 시점과 폴링 주기에만 불린다
(요청은 레지스트리의 dict 조회로 끝난다, §6).
"""

from sqlalchemy import func, select

from gateway.domain.models.guardrail import Guardrail
from gateway.infrastructure.mappers.guardrail import to_domain
from gateway.infrastructure.models.guardrail import GuardrailModel


class SessionScopedGuardrailSource:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def latest_versions(self) -> dict[str, int]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    # 그래프 컬럼을 읽지 않는다. 폴링은 번호만 비교하면 된다.
                    select(
                        GuardrailModel.name,
                        func.max(GuardrailModel.version_number),
                    )
                    .where(GuardrailModel.version_number.is_not(None))
                    .group_by(GuardrailModel.name)
                )
            ).all()
        return {name: version for name, version in rows}

    async def load_published(self, name: str, version_number: int) -> Guardrail | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(GuardrailModel).where(
                        GuardrailModel.name == name,
                        GuardrailModel.version_number == version_number,
                    )
                )
            ).scalar_one_or_none()
        return to_domain(row) if row is not None else None
