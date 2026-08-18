"""SQLAlchemy Guardrail dao.

Aggregates in SQL rather than in Python: the list screen wants one row per
guardrail, but the table holds one row per version. Loading every version to fold
them in the application would read the whole graph column for rows we then throw
away.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.guardrail.definition.application.result.guardrail_result import (
    GuardrailDetail,
    GuardrailSummary,
)
from gateway.guardrail.definition.infrastructure.guardrail_model import GuardrailModel
from gateway.guardrail.domain.models.guardrail import DRAFT_VERSION


class SqlAlchemyGuardrailDao:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_detail(self, name: str, version: str) -> GuardrailDetail | None:
        row = (
            await self._session.execute(
                select(GuardrailModel).where(
                    GuardrailModel.name == name,
                    GuardrailModel.version == version,
                )
            )
        ).scalar_one_or_none()
        return GuardrailDetail.model_validate(row) if row is not None else None

    async def get_latest_detail(self, name: str) -> GuardrailDetail | None:
        row = (
            await self._session.execute(
                select(GuardrailModel)
                .where(
                    GuardrailModel.name == name,
                    # version 문자열로 정렬하면 '10' < '9' 가 된다.
                    GuardrailModel.version_number.is_not(None),
                )
                .order_by(GuardrailModel.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return GuardrailDetail.model_validate(row) if row is not None else None

    async def list_summaries(self) -> tuple[list[GuardrailSummary], int]:
        """One row per name.

        Pagination is not implemented yet, so ``total`` equals ``len(items)``. It
        is in the signature because the wire shape is ``Page[GuardrailSummary]``
        and adding the field later would be a breaking change.
        """
        rows = (
            await self._session.execute(
                select(
                    GuardrailModel.name,
                    func.max(GuardrailModel.version_number).label("latest_version_number"),
                    func.bool_or(GuardrailModel.version == DRAFT_VERSION).label("has_draft"),
                    # 이름 단위 최신 시각. 발행본이 draft 보다 새로울 수 있다.
                    func.max(GuardrailModel.updated_at).label("updated_at"),
                )
                .group_by(GuardrailModel.name)
                # 순서가 없으면 목록 화면이 요청마다 흔들린다.
                .order_by(GuardrailModel.name)
            )
        ).all()

        items = [GuardrailSummary.model_validate(row) for row in rows]
        return items, len(items)
