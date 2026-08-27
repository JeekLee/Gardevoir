"""SQLAlchemy Guardrail repository."""

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.guardrail.domain.exceptions.guardrail_error import GuardrailError
from gateway.guardrail.domain.models.guardrail import DRAFT_VERSION, Guardrail
from gateway.guardrail.infrastructure.mapper.guardrail_mapper import to_domain, to_model
from gateway.guardrail.infrastructure.model.guardrail_model import GuardrailModel


class SqlAlchemyGuardrailRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, guardrail: Guardrail, *, id: str) -> None:
        self._session.add(to_model(guardrail, id=id))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # 서비스가 미리 확인하지만 확인과 제약 사이에는 틈이 있다. 동시 요청
            # 두 개가 그 틈에 들어오면 지는 쪽이 500 이 아니라 409 를 받아야 한다.
            # 번역이 리포지토리에 있는 이유: IntegrityError 는 SQLAlchemy 타입이고,
            # application 은 그것을 알아서는 안 된다.
            if guardrail.is_draft:
                raise GuardrailError.NAME_TAKEN.exception(details={"name": guardrail.name}) from exc
            raise GuardrailError.CONCURRENT_WRITE.exception(
                details={"name": guardrail.name, "version": guardrail.version}
            ) from exc

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
        replacement = to_model(guardrail, id=row.id)
        row.description = replacement.description
        row.graph = replacement.graph
        await self._session.flush()

    async def next_version_number(self, name: str) -> int:
        highest = (
            await self._session.execute(
                select(func.max(GuardrailModel.version_number)).where(GuardrailModel.name == name)
            )
        ).scalar_one()
        return (highest or 0) + 1

    async def delete(self, name: str) -> None:
        await self._session.execute(delete(GuardrailModel).where(GuardrailModel.name == name))
        await self._session.flush()

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
