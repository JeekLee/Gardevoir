"""SQLAlchemy Guardrail repository."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import DRAFT_VERSION, Guardrail
from gateway.infrastructure.mappers.guardrail import to_domain, to_model
from gateway.infrastructure.models.guardrail import GuardrailModel


class SqlAlchemyGuardrailRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, guardrail: Guardrail, *, id: str) -> None:
        self._session.add(to_model(guardrail, id=id))
        await self._session.flush()

    async def exists(self, name: str) -> bool:
        # draft 뿐 아니라 발행본까지 본다 — 발행만 남은 이름도 점유 상태다.
        found = (
            await self._session.execute(
                select(GuardrailModel.id).where(GuardrailModel.name == name).limit(1)
            )
        ).scalar_one_or_none()
        return found is not None

    async def find_draft(self, name: str) -> Guardrail | None:
        return await self._find(name, DRAFT_VERSION)

    async def find_published(
        self, name: str, version_number: int | None = None
    ) -> Guardrail | None:
        if version_number is not None:
            return await self._find(name, str(version_number))

        row = (
            await self._session.execute(
                select(GuardrailModel)
                .where(
                    GuardrailModel.name == name,
                    # 문자열 version 으로 정렬하면 '10' < '9' 가 된다.
                    GuardrailModel.version_number.is_not(None),
                )
                .order_by(GuardrailModel.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return to_domain(row) if row is not None else None

    async def replace_draft(self, guardrail: Guardrail) -> None:
        """Overwrite the draft row in place, leaving published rows alone (§6)."""
        row = await self._row(guardrail.name, DRAFT_VERSION)
        if row is None:
            GuardrailError.NO_DRAFT.raise_(details={"name": guardrail.name})
        row.graph = to_model(guardrail, id=row.id).graph
        await self._session.flush()

    async def next_version_number(self, name: str) -> int:
        highest = (
            await self._session.execute(
                select(func.max(GuardrailModel.version_number)).where(GuardrailModel.name == name)
            )
        ).scalar_one()
        return (highest or 0) + 1

    # -- helpers ------------------------------------------------------------

    async def _find(self, name: str, version: str) -> Guardrail | None:
        row = await self._row(name, version)
        return to_domain(row) if row is not None else None

    async def _row(self, name: str, version: str) -> GuardrailModel | None:
        return (
            await self._session.execute(
                select(GuardrailModel).where(
                    GuardrailModel.name == name,
                    GuardrailModel.version == version,
                )
            )
        ).scalar_one_or_none()
