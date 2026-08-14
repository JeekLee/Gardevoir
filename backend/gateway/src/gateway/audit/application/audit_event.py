"""Audit event.

Mirrors the audit_events schema in §10, but knows nothing about how it is
stored: column order and row conversion belong to the sink, so swapping the
sink does not change this type.

Not a CamelModel — it never crosses the HTTP boundary, and Pydantic validation
has no business on the request path (§11.8).
"""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from ulid import ULID


class Checkpoint(StrEnum):
    """Where a verdict was reached (§3). NONE means no inspection ran."""

    INPUT = "input"
    TOOL_RESULT = "tool_result"
    OUTPUT = "output"
    TOOL_CALL = "tool_call"
    NONE = ""


def new_event_id() -> str:
    """ULID — time-ordered and unique, so ids sort by creation."""
    return str(ULID())


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    created_at: dt.datetime
    request_id: str
    api_key_id: str
    app_name: str
    guardrail: str
    guardrail_version: int
    mode: str
    action: str
    checkpoint: Checkpoint
    checks_fired: tuple[str, ...]
    verdicts: str
    tier_reached: str
    tainted: bool
    latency_ms: float
    model: str
    prompt_tokens: int
    completion_tokens: int
