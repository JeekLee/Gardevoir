import datetime as dt

from gateway.audit.application.dao.audit_dao import AuditDao, AuditFilter
from gateway.audit.application.result.audit_result import AuditInsights


class AuditService:
    def __init__(self, *, audit_dao: AuditDao) -> None:
        self._audit_dao = audit_dao

    async def insights(self, audit_filter: AuditFilter, *, top_n: int) -> AuditInsights:
        duration = audit_filter.to_at - audit_filter.from_at
        if duration <= dt.timedelta(days=1):
            bucket_seconds = 60 * 60
        elif duration <= dt.timedelta(days=7):
            bucket_seconds = 6 * 60 * 60
        else:
            bucket_seconds = 24 * 60 * 60
        return await self._audit_dao.insights(
            audit_filter,
            bucket_seconds=bucket_seconds,
            top_n=top_n,
        )
