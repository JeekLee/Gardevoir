"""Guardrail test results."""

from gateway.guardrail.domain.models.guardrail import VerdictAction
from shared_kernel.api import CamelModel


class TestCheckpointResult(CamelModel):
    ran: bool
    would_have: VerdictAction | None
    checks_fired: list[str]
    masked: bool
    evidence: list[dict]
    tier: str


class TestCheckpoints(CamelModel):
    input: TestCheckpointResult
    tool_result: TestCheckpointResult
    output: TestCheckpointResult
    tool_call: TestCheckpointResult


class TestModelResponse(CamelModel):
    content: str
    tool_calls: list[dict]
    masked_preview: str | None


class GuardrailTestResult(CamelModel):
    guardrail: str
    version: str
    model: str
    checkpoints: TestCheckpoints
    overall_would_have: VerdictAction
    model_response: TestModelResponse
    audit_id: None = None
    latency_ms: float
