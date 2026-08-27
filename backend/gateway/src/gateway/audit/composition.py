from fastapi import Request

from gateway.audit.application.dao.audit_dao import AuditDao
from gateway.audit.infrastructure.dao.clickhouse_audit_dao import ClickHouseAuditDao


def provide_audit_dao(request: Request) -> AuditDao:
    return ClickHouseAuditDao(request.app.state.clickhouse_session_factory)
