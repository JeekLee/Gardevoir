"""Audit sink port.

Append-only. The adapter decides batching and storage (§10).
"""

from typing import Protocol

from gateway.application.audit.audit_event import AuditEvent


class AuditSink(Protocol):
    async def submit(self, event: AuditEvent) -> None: ...
