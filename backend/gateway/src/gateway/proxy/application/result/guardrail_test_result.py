"""Guardrail test results."""

from gateway.guardrail.domain.models.guardrail import VerdictAction
from shared_kernel.api import CamelModel


class TestCheckpointResult(CamelModel):
    ran: bool
    action: VerdictAction
    checks_fired: list[str]
    masked: bool
    evidence: list[dict]
    tier: str
    raw_text: str | None
    applied_text: str | None


class TestCheckpoints(CamelModel):
    input: TestCheckpointResult
    tool_result: TestCheckpointResult
    output: TestCheckpointResult
    tool_call: TestCheckpointResult


class GuardrailTestResult(CamelModel):
    guardrail: str
    version: str
    model: str
    checkpoints: TestCheckpoints
    overall_action: VerdictAction
    blocked: bool
    blocked_at: str | None
    blocked_reason: str | None
    raw_content: str
    applied_content: str
    tool_calls: list[dict]
    audit_id: None = None
    latency_ms: float
    unmaskable: int = 0
