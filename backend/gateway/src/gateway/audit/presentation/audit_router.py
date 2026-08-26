from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import AwareDatetime

from gateway.audit.application.dao.audit_dao import AuditCursor, AuditDao, AuditFilter
from gateway.audit.application.result.audit_result import (
    AuditEventDetail,
    AuditEventPage,
    AuditSummary,
)
from gateway.audit.composition import provide_audit_dao
from shared_kernel.api import JsonResponse
from shared_kernel.auth import AccessTokenClaims, Role, require_role

router = APIRouter(prefix="/audit", tags=["audit"], default_response_class=JsonResponse)


def _audit_filter(
    app_name: Annotated[str | None, Query(alias="appName", max_length=255)] = None,
    guardrail: Annotated[str | None, Query(max_length=255)] = None,
    action: Annotated[
        Literal["allow", "mask", "blocked", "approval_required"] | None,
        Query(),
    ] = None,
    checkpoint: Annotated[
        Literal["input", "tool_result", "output", "tool_call"] | None,
        Query(),
    ] = None,
    mode: Annotated[Literal["enforce", "dry-run"] | None, Query()] = None,
    tainted: Annotated[bool | None, Query()] = None,
    from_at: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_at: Annotated[AwareDatetime | None, Query(alias="to")] = None,
) -> AuditFilter:
    if from_at is not None and to_at is not None and from_at > to_at:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")
    return AuditFilter(
        app_name=app_name,
        guardrail=guardrail,
        action=action,
        checkpoint=checkpoint,
        mode=mode,
        tainted=tainted,
        from_at=from_at,
        to_at=to_at,
    )


@router.get("")
async def list_audit_events(
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    audit_filter: Annotated[AuditFilter, Depends(_audit_filter)],
    audit_dao: Annotated[AuditDao, Depends(provide_audit_dao)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> AuditEventPage:
    try:
        decoded_cursor = AuditCursor.decode(cursor) if cursor is not None else None
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid audit cursor") from None
    items, next_cursor = await audit_dao.list_events(
        audit_filter, limit=limit, cursor=decoded_cursor
    )
    return AuditEventPage(
        items=items,
        next_cursor=next_cursor.encode() if next_cursor is not None else None,
    )


@router.get("/summary")
async def summarize_audit_events(
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    audit_filter: Annotated[AuditFilter, Depends(_audit_filter)],
    audit_dao: Annotated[AuditDao, Depends(provide_audit_dao)],
) -> AuditSummary:
    return await audit_dao.summary(audit_filter)


@router.get("/{event_id}")
async def get_audit_event(
    event_id: Annotated[str, Path(min_length=1, max_length=64)],
    _: Annotated[AccessTokenClaims, Depends(require_role(Role.ADMIN))],
    audit_dao: Annotated[AuditDao, Depends(provide_audit_dao)],
) -> AuditEventDetail:
    event = await audit_dao.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="audit event not found")
    return event
