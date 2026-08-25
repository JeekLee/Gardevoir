"""Test an authored guardrail against a real upstream response."""

import orjson

from gateway.guardrail.definition.application.dao.guardrail_dao import GuardrailDao
from gateway.guardrail.domain.exceptions.guardrail_error import GuardrailError
from gateway.guardrail.domain.models.guardrail import (
    DRAFT_VERSION,
    Guardrail,
    NodeType,
    VerdictAction,
    require_valid_name,
)
from gateway.guardrail.inspection.application.outcome import Inspection
from gateway.guardrail.plan.application.compiler import compile_guardrail
from gateway.proxy.application.command.guardrail_test_command import TestGuardrail
from gateway.proxy.application.result.guardrail_test_result import (
    GuardrailTestResult,
    TestCheckpointResult,
    TestCheckpoints,
)
from gateway.proxy.application.service.proxy_service import ProxyService

_SEVERITY = {
    VerdictAction.ALLOW: 0,
    VerdictAction.MASK: 1,
    VerdictAction.BLOCK: 2,
}


class GuardrailTestService:
    def __init__(self, *, guardrail_dao: GuardrailDao, proxy_service: ProxyService) -> None:
        self._guardrail_dao = guardrail_dao
        self._proxy_service = proxy_service

    async def test(self, name: str, cmd: TestGuardrail) -> GuardrailTestResult:
        require_valid_name(name)
        detail = await self._guardrail_dao.get_detail(name, cmd.version)
        if detail is None:
            error = (
                GuardrailError.NO_DRAFT
                if cmd.version == DRAFT_VERSION
                else GuardrailError.NOT_FOUND
            )
            error.raise_(details={"name": name, "version": cmd.version})

        guardrail = Guardrail.from_graph(
            name=detail.name,
            version=detail.version,
            version_number=detail.version_number,
            graph=detail.graph,
        )
        guardrail.validate()
        plan = compile_guardrail(guardrail)
        completion = await self._proxy_service.test(
            plan=plan,
            payload=orjson.dumps({"model": cmd.model, "messages": cmd.messages, "stream": False}),
        )

        verdicts = _verdicts(guardrail)
        checkpoints = TestCheckpoints(
            input=_checkpoint(completion.input, verdicts),
            tool_result=_checkpoint(completion.tool_result, verdicts),
            output=_checkpoint(completion.output, verdicts),
            tool_call=_checkpoint(completion.tool_call, verdicts),
        )
        blocked_at, blocked_reason = _blocked(checkpoints)
        blocked = blocked_at is not None
        return GuardrailTestResult(
            guardrail=detail.name,
            version=detail.version,
            model=cmd.model,
            checkpoints=checkpoints,
            overall_action=_overall(checkpoints),
            blocked=blocked,
            blocked_at=blocked_at,
            blocked_reason=blocked_reason,
            raw_content=_content(completion.raw_response),
            applied_content="" if blocked else _content(completion.applied_response),
            tool_calls=_tool_calls(completion.raw_response),
            latency_ms=completion.latency_ms,
        )


def _verdicts(guardrail: Guardrail) -> dict[str, tuple[str, VerdictAction]]:
    result = {}
    for node in guardrail.nodes:
        if node.type is not NodeType.VERDICT:
            continue
        code = node.config.get("code")
        result[node.id] = (
            code if isinstance(code, str) and code else node.id,
            VerdictAction(node.config["action"]),
        )
    return result


def _checkpoint(
    inspection: Inspection,
    verdicts: dict[str, tuple[str, VerdictAction]],
) -> TestCheckpointResult:
    fired = {
        node_id: verdicts.get(node_id, (node_id, VerdictAction.ALLOW))
        for node_id in inspection.checks_fired
    }
    return TestCheckpointResult(
        ran=inspection.ran,
        action=(
            VerdictAction.BLOCK
            if inspection.blocked
            else VerdictAction.MASK
            if inspection.masked
            else VerdictAction.ALLOW
        ),
        checks_fired=[code for code, _ in fired.values()],
        masked=inspection.masked,
        evidence=list(inspection.evidence),
        tier=inspection.tier,
    )


def _overall(checkpoints: TestCheckpoints) -> VerdictAction:
    return max(
        (
            checkpoints.input.action,
            checkpoints.tool_result.action,
            checkpoints.output.action,
            checkpoints.tool_call.action,
        ),
        key=_SEVERITY.get,
    )


def _blocked(checkpoints: TestCheckpoints) -> tuple[str | None, str | None]:
    ordered = (
        ("input", checkpoints.input),
        ("toolResult", checkpoints.tool_result),
        ("output", checkpoints.output),
        ("toolCall", checkpoints.tool_call),
    )
    for name, checkpoint in ordered:
        if checkpoint.action is VerdictAction.BLOCK:
            return name, checkpoint.checks_fired[0] if checkpoint.checks_fired else None
    return None, None


def _message(response: object) -> dict:
    if not isinstance(response, dict):
        return {}
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, dict) else {}


def _content(response: object) -> str:
    content = _message(response).get("content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return orjson.dumps(content).decode()


def _tool_calls(response: object) -> list[dict]:
    calls = _message(response).get("tool_calls")
    if not isinstance(calls, list):
        return []
    return [call for call in calls if isinstance(call, dict)]
