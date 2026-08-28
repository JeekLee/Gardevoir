import base64
import datetime as dt
from dataclasses import dataclass
from typing import Protocol

import orjson

from gateway.audit.application.result.audit_result import (
    AuditEventDetail,
    AuditEventSummary,
    AuditInsights,
    AuditSummary,
)


@dataclass(frozen=True, slots=True)
class AuditFilter:
    from_at: dt.datetime
    to_at: dt.datetime
    app_name: str | None = None
    guardrail: str | None = None
    action: str | None = None
    checkpoint: str | None = None
    mode: str | None = None
    tainted: bool | None = None
    check: str | None = None


@dataclass(frozen=True, slots=True)
class AuditCursor:
    created_at: dt.datetime
    event_id: str

    def encode(self) -> str:
        payload = orjson.dumps({"createdAt": self.created_at.isoformat(), "id": self.event_id})
        return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()

    @classmethod
    def decode(cls, value: str) -> AuditCursor:
        try:
            padding = b"=" * (-len(value) % 4)
            payload = orjson.loads(base64.urlsafe_b64decode(value.encode() + padding))
            created_at = dt.datetime.fromisoformat(payload["createdAt"])
            event_id = payload["id"]
        except (KeyError, TypeError, ValueError, orjson.JSONDecodeError) as exc:
            raise ValueError("invalid audit cursor") from exc
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("invalid audit cursor")
        return cls(created_at=created_at, event_id=event_id)


class AuditDao(Protocol):
    async def list_events(
        self,
        audit_filter: AuditFilter,
        *,
        limit: int,
        cursor: AuditCursor | None,
    ) -> tuple[list[AuditEventSummary], AuditCursor | None]: ...

    async def get_event(self, event_id: str) -> AuditEventDetail | None: ...

    async def summary(self, audit_filter: AuditFilter) -> AuditSummary: ...

    async def insights(
        self,
        audit_filter: AuditFilter,
        *,
        bucket_seconds: int,
        top_n: int,
    ) -> AuditInsights: ...
