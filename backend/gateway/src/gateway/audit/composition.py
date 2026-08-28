from fastapi import Request

from gateway.audit.application.dao.audit_dao import AuditDao
from gateway.audit.application.service.audit_service import AuditService
from gateway.audit.infrastructure.dao.clickhouse_audit_dao import ClickHouseAuditDao


def provide_audit_dao(request: Request) -> AuditDao:
    return ClickHouseAuditDao(request.app.state.clickhouse_session_factory)


def provide_audit_service(request: Request) -> AuditService:
    return AuditService(audit_dao=provide_audit_dao(request))
