"""Test an authored guardrail against a real upstream response."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import orjson

from gateway.guardrail.application.compiler import compile_guardrail
from gateway.guardrail.application.dao.guardrail_dao import GuardrailDao
from gateway.guardrail.application.outcome import Inspection
from gateway.guardrail.application.result.guardrail_result import GuardrailDetail
from gateway.guardrail.domain.exceptions.guardrail_error import GuardrailError
from gateway.guardrail.domain.models.execution_plan import ExecutionPlan
from gateway.guardrail.domain.models.guardrail import (
    DRAFT_VERSION,
    Guardrail,
    NodeType,
    VerdictAction,
    require_valid_name,
)
from gateway.proxy.application.command.guardrail_test_command import TestGuardrail
from gateway.proxy.application.result.guardrail_test_result import (
    GuardrailTestPre,
    GuardrailTestResult,
    TestCheckpointResult,
    TestCheckpoints,
)
from gateway.proxy.application.service.proxy_service import (
    GuardrailTestProxyStream,
    GuardrailTestStreamingCompletion,
    GuardrailTestStreamingPre,
    ProxyService,
)

_SEVERITY = {
    VerdictAction.ALLOW: 0,
    VerdictAction.MASK: 1,
    VerdictAction.BLOCK: 2,
}


@dataclass(slots=True)
class GuardrailTestStream:
    status_code: int
    media_type: str
    _chunks: AsyncIterator[bytes] = field(repr=False)
    _pre: GuardrailTestPre = field(repr=False)
    _result: Callable[[], GuardrailTestResult] = field(repr=False)

    def aiter(self) -> AsyncIterator[bytes]:
        return self._chunks

    def pre(self) -> GuardrailTestPre:
        return self._pre

    def result(self) -> GuardrailTestResult:
        return self._result()


class GuardrailTestService:
    def __init__(self, *, guardrail_dao: GuardrailDao, proxy_service: ProxyService) -> None:
        self._guardrail_dao = guardrail_dao
        self._proxy_service = proxy_service

    async def test(self, name: str, cmd: TestGuardrail) -> GuardrailTestResult:
        detail, guardrail, plan = await self._prepare(name, cmd.version)
        completion = await self._proxy_service.test(
            plan=plan,
            mode=cmd.mode,
            payload=orjson.dumps(_payload(cmd, stream=False)),
        )

        blocked = completion.blocked_before_upstream or completion.blocked_after_upstream
        return _result(
            detail=detail,
            guardrail=guardrail,
            model=cmd.model,
            input_inspection=completion.input,
            tool_result_inspection=completion.tool_result,
            input_raw_text=completion.input_text.raw,
            input_applied_text=completion.input_text.applied,
            tool_result_raw_text=completion.tool_result_text.raw,
            tool_result_applied_text=completion.tool_result_text.applied,
            output_inspection=completion.output,
            tool_call_inspection=completion.tool_call,
            raw_content=_content(completion.raw_response),
            applied_content="" if blocked else _content(completion.applied_response),
            tool_calls=_tool_calls(completion.raw_response),
            latency_ms=completion.latency_ms,
        )

    @asynccontextmanager
    async def stream(self, name: str, cmd: TestGuardrail) -> AsyncIterator[GuardrailTestStream]:
        """Compile before opening SSE, then relay the draft through the requested mode."""
        detail, guardrail, plan = await self._prepare(name, cmd.version)
        payload = orjson.dumps(_payload(cmd, stream=True))
        cm = self._proxy_service.test_stream(plan=plan, mode=cmd.mode, payload=payload)
        proxy_stream = await cm.__aenter__()
        try:
            yield GuardrailTestStream(
                status_code=proxy_stream.status_code,
                media_type=proxy_stream.media_type,
                _chunks=proxy_stream.aiter(),
                _pre=_stream_pre(guardrail=guardrail, pre=proxy_stream.pre()),
                _result=lambda: _stream_result(
                    detail=detail,
                    guardrail=guardrail,
                    model=cmd.model,
                    stream=proxy_stream,
                ),
            )
        finally:
            await cm.__aexit__(None, None, None)

    async def _prepare(
        self, name: str, version: str
    ) -> tuple[GuardrailDetail, Guardrail, ExecutionPlan]:
        require_valid_name(name)
        detail = await self._guardrail_dao.get_detail(name, version)
        if detail is None:
            error = (
                GuardrailError.NO_DRAFT if version == DRAFT_VERSION else GuardrailError.NOT_FOUND
            )
            error.raise_(details={"name": name, "version": version})

        guardrail = Guardrail.from_graph(
            name=detail.name,
            version=detail.version,
            version_number=detail.version_number,
            description=detail.description,
            graph=detail.graph,
        )
        guardrail.validate()
        return detail, guardrail, compile_guardrail(guardrail)


def _payload(cmd: TestGuardrail, *, stream: bool) -> dict:
    payload = {"model": cmd.model, "messages": cmd.messages, "stream": stream}
    if cmd.tools is not None:
        payload["tools"] = cmd.tools
    if cmd.tool_choice is not None:
        payload["tool_choice"] = cmd.tool_choice
    return payload


def _stream_pre(*, guardrail: Guardrail, pre: GuardrailTestStreamingPre) -> GuardrailTestPre:
    verdicts = _verdicts(guardrail)
    return GuardrailTestPre(
        input=_checkpoint(
            pre.input,
            verdicts,
            raw_text=pre.input_text.raw,
            applied_text=pre.input_text.applied,
        ),
        tool_result=_checkpoint(
            pre.tool_result,
            verdicts,
            raw_text=pre.tool_result_text.raw,
            applied_text=pre.tool_result_text.applied,
        ),
    )


def _stream_result(
    *,
    detail: GuardrailDetail,
    guardrail: Guardrail,
    model: str,
    stream: GuardrailTestProxyStream,
) -> GuardrailTestResult:
    completion: GuardrailTestStreamingCompletion = stream.result()
    return _result(
        detail=detail,
        guardrail=guardrail,
        model=model,
        input_inspection=completion.input,
        tool_result_inspection=completion.tool_result,
        input_raw_text=completion.input_text.raw,
        input_applied_text=completion.input_text.applied,
        tool_result_raw_text=completion.tool_result_text.raw,
        tool_result_applied_text=completion.tool_result_text.applied,
        output_inspection=completion.output,
        tool_call_inspection=completion.tool_call,
        raw_content="",
        applied_content=completion.applied_content,
        tool_calls=completion.tool_calls,
        latency_ms=completion.latency_ms,
        unmaskable=completion.unmaskable,
    )


def _result(
    *,
    detail: GuardrailDetail,
    guardrail: Guardrail,
    model: str,
    input_inspection: Inspection,
    tool_result_inspection: Inspection,
    input_raw_text: str,
    input_applied_text: str,
    tool_result_raw_text: str,
    tool_result_applied_text: str,
    output_inspection: Inspection,
    tool_call_inspection: Inspection,
    raw_content: str,
    applied_content: str,
    tool_calls: list[dict],
    latency_ms: float,
    unmaskable: int = 0,
) -> GuardrailTestResult:
    verdicts = _verdicts(guardrail)
    checkpoints = TestCheckpoints(
        input=_checkpoint(
            input_inspection,
            verdicts,
            raw_text=input_raw_text,
            applied_text=input_applied_text,
        ),
        tool_result=_checkpoint(
            tool_result_inspection,
            verdicts,
            raw_text=tool_result_raw_text,
            applied_text=tool_result_applied_text,
        ),
        output=_checkpoint(output_inspection, verdicts, raw_text=None, applied_text=None),
        tool_call=_checkpoint(tool_call_inspection, verdicts, raw_text=None, applied_text=None),
    )
    blocked_at, blocked_reason = _blocked(checkpoints)
    return GuardrailTestResult(
        guardrail=detail.name,
        version=detail.version,
        model=model,
        checkpoints=checkpoints,
        overall_action=_overall(checkpoints),
        blocked=blocked_at is not None,
        blocked_at=blocked_at,
        blocked_reason=blocked_reason,
        raw_content=raw_content,
        applied_content=applied_content,
        tool_calls=tool_calls,
        latency_ms=latency_ms,
        unmaskable=unmaskable,
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
    *,
    raw_text: str | None,
    applied_text: str | None,
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
        raw_text=raw_text,
        applied_text=applied_text,
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
