"""Privacy-aware audit content capture (§10)."""

from dataclasses import dataclass
from hashlib import sha256

import orjson

from gateway.audit.application.model.audit_event import Checkpoint
from gateway.guardrail.application.outcome import MASK_PLACEHOLDER
from gateway.guardrail.application.provenance import extract_tool_calls
from gateway.guardrail.application.service.inspector import Inspector
from gateway.guardrail.application.text import (
    extract_input_text,
    extract_output_texts,
    extract_tool_result_text,
)
from gateway.guardrail.domain.models.execution_plan import (
    All,
    ExecutionPlan,
    Program,
    RegexSet,
    Verdict,
)


@dataclass(frozen=True, slots=True)
class AuditContent:
    content_fingerprint: str
    excerpt: str
    input_body: str
    output_body: str
    tool_calls_body: str


def capture_audit_content(
    *,
    request_payload: bytes,
    response_body: object | bytes | None,
    plan: ExecutionPlan | None,
    checkpoint: Checkpoint,
    checks_fired: tuple[str, ...],
    tool_evidence: tuple[dict, ...],
    store_bodies: bool,
    excerpt_max_chars: int,
) -> AuditContent:
    """Capture the always-on fingerprint/excerpt and optional full bodies."""
    request = _decode_body(request_payload)
    response = _decode_body(response_body)
    excerpt = _excerpt(
        request=request,
        response=response,
        plan=plan,
        checkpoint=checkpoint,
        checks_fired=checks_fired,
        tool_evidence=tool_evidence,
        max_chars=excerpt_max_chars,
    )
    if not store_bodies:
        return AuditContent(
            content_fingerprint=sha256(request_payload).hexdigest(),
            excerpt=excerpt,
            input_body="",
            output_body="",
            tool_calls_body="",
        )

    return AuditContent(
        content_fingerprint=sha256(request_payload).hexdigest(),
        excerpt=excerpt,
        input_body=_serialize_body(request),
        output_body=_serialize_body(response),
        tool_calls_body=orjson.dumps(
            _audit_tool_calls(request) + _audit_tool_calls(response)
        ).decode(),
    )


def _decode_body(body: object | bytes | None) -> object | None:
    if not isinstance(body, bytes):
        return body
    try:
        return orjson.loads(body)
    except orjson.JSONDecodeError:
        return body.decode(errors="replace")


def _serialize_body(body: object | None) -> str:
    return "" if body is None else orjson.dumps(body).decode()


def _audit_tool_calls(body: object) -> list[dict]:
    calls = []
    if isinstance(body, dict):
        messages = body.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                message_calls = message.get("tool_calls")
                if isinstance(message_calls, list):
                    calls.extend(call for call in message_calls if isinstance(call, dict))
    calls.extend(extract_tool_calls(body))
    return [_audit_tool_call(call) for call in calls]


def _audit_tool_call(call: dict) -> dict:
    function = call.get("function")
    if not isinstance(function, dict):
        return {"name": "", "arguments": ""}
    name = function.get("name")
    arguments = function.get("arguments")
    return {
        "name": name if isinstance(name, str) else "",
        "arguments": arguments if isinstance(arguments, (str, dict, list)) else "",
    }


def _excerpt(
    *,
    request: object,
    response: object,
    plan: ExecutionPlan | None,
    checkpoint: Checkpoint,
    checks_fired: tuple[str, ...],
    tool_evidence: tuple[dict, ...],
    max_chars: int,
) -> str:
    if not checks_fired:
        return ""
    if checkpoint is Checkpoint.TOOL_CALL:
        evidence = orjson.dumps(tool_evidence).decode() if tool_evidence else ""
        return evidence[:max_chars]
    if plan is None:
        return ""

    program = plan.program_for(str(checkpoint))
    if program is None:
        return ""
    text = _checkpoint_text(checkpoint, request, response)
    if not text:
        return ""
    spans = _evidence_spans(program, checks_fired, text)
    return _masked_excerpt(text, spans, max_chars=max_chars)


def _checkpoint_text(checkpoint: Checkpoint, request: object, response: object) -> str:
    if checkpoint is Checkpoint.INPUT:
        return extract_input_text(request)
    if checkpoint is Checkpoint.TOOL_RESULT:
        return extract_tool_result_text(request)
    if checkpoint is Checkpoint.OUTPUT:
        return "\n".join(text for _, text in extract_output_texts(response))
    return ""


def _evidence_spans(
    program: Program, checks_fired: tuple[str, ...], text: str
) -> list[tuple[int, int]]:
    spans = Inspector.mask_spans(program, checks_fired, text)
    patterns = _verdict_patterns(program, checks_fired)
    spans.extend(
        (match.start(), match.end()) for pattern in patterns for match in pattern.finditer(text)
    )
    return _merge_spans(spans)


def _verdict_patterns(program: Program, checks_fired: tuple[str, ...]) -> list[object]:
    producers: dict[int, object] = {}
    verdicts: dict[str, Verdict] = {}
    for instruction in program.instructions:
        if isinstance(instruction, Verdict):
            verdicts[instruction.node_id] = instruction
        elif isinstance(instruction, RegexSet):
            producers.update((slot, instruction) for slot in instruction.outs)
        elif hasattr(instruction, "out"):
            producers[instruction.out] = instruction

    pattern_slots: set[int] = set()
    pending = [slot for check in checks_fired if check in verdicts for slot in verdicts[check].srcs]
    seen: set[int] = set()
    while pending:
        slot = pending.pop()
        if slot in seen:
            continue
        seen.add(slot)
        if slot in program.patterns_by_slot:
            pattern_slots.add(slot)
            continue
        producer = producers.get(slot)
        if isinstance(producer, All):
            pending.extend(producer.srcs)

    return [program.patterns_by_slot[slot] for slot in sorted(pattern_slots)]


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _masked_excerpt(text: str, spans: list[tuple[int, int]], *, max_chars: int) -> str:
    if not spans:
        return ""
    first_start, first_end = spans[0]
    context = max(0, max_chars - len(MASK_PLACEHOLDER) - 2)
    start = max(0, first_start - context // 2)
    end = min(len(text), first_end + context - (first_start - start))
    local_spans = [
        (max(span_start, start) - start, min(span_end, end) - start)
        for span_start, span_end in spans
        if span_start < end and span_end > start
    ]
    excerpt = text[start:end]
    for span_start, span_end in reversed(local_spans):
        excerpt = excerpt[:span_start] + MASK_PLACEHOLDER + excerpt[span_end:]
    excerpt = ("…" if start else "") + excerpt + ("…" if end < len(text) else "")
    return excerpt if len(excerpt) <= max_chars else MASK_PLACEHOLDER


__all__ = ["AuditContent", "capture_audit_content"]
