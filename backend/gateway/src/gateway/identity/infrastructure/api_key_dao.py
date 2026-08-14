"""SQLAlchemy ApiKey read model.

**시크릿을 투영하지 않는다.** ``key_hash`` 도 ``upstream_api_key`` 도 result DTO 에
자리가 없다 — 후자는 프로바이더 시크릿이라 관리 화면에 흘리면 안 된다. 여기서
매핑하지 않는 것이 그것을 보장하는 유일한 지점이다.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.identity.application.api_key_result import ApiKeySummary
from gateway.identity.domain.models.api_key import Scope
from gateway.identity.infrastructure.api_key_model import ApiKeyModel


def _summary(row: ApiKeyModel) -> ApiKeySummary:
    return ApiKeySummary(
        id=row.id,
        name=row.name,
        upstream_base_url=row.upstream_base_url,
        has_upstream_key=bool(row.upstream_api_key),
        allowed_guardrails=list(row.allowed_guardrails or ()),
        default_guardrail=row.default_guardrail,
        scopes=[Scope(s) for s in (row.scopes or []) if s in set(Scope)],
        disabled=row.disabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyApiKeyDao:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self, key_id: str) -> ApiKeySummary | None:
        row = await self._session.get(ApiKeyModel, key_id)
        return _summary(row) if row is not None else None

    async def list_summaries(self) -> tuple[list[ApiKeySummary], int]:
        rows = (
            (await self._session.execute(select(ApiKeyModel).order_by(ApiKeyModel.created_at)))
            .scalars()
            .all()
        )
        return [_summary(row) for row in rows], len(rows)

    async def exists_with_name(self, name: str) -> bool:
        return bool(
            await self._session.scalar(
                select(func.count()).select_from(ApiKeyModel).where(ApiKeyModel.name == name)
            )
        )
