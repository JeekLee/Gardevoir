from datetime import datetime

from pydantic import JsonValue

from shared_kernel.api import CamelModel


class AuditEventSummary(CamelModel):
    id: str
    created_at: datetime
    app_name: str
    guardrail: str
    guardrail_version: int
    mode: str
    action: str
    checkpoint: str
    checks_fired: list[str]
    tier_reached: str
    tainted: bool
    latency_ms: float
    model: str


class AuditEventDetail(AuditEventSummary):
    request_id: str
    api_key_id: str
    verdicts: JsonValue
    prompt_tokens: int
    completion_tokens: int
    content_fingerprint: str
    excerpt: str
    input_body: str
    output_body: str
    tool_calls_body: str


class AuditSummary(CamelModel):
    counts_by_action: dict[str, int]
    latency_p50: float
    latency_p95: float
    total: int


class AuditEventPage(CamelModel):
    items: list[AuditEventSummary]
    next_cursor: str | None
