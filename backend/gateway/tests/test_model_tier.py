"""Model-tier merge and input-path integration tests."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import orjson

from gateway.audit.application.model.audit_event import AuditEvent
from gateway.guardrail.application.compiler import compile_guardrail
from gateway.guardrail.application.outcome import TIER_MODEL, TIER_RULES, Inspection
from gateway.guardrail.application.port.model_judge import JudgeRequest, JudgeResult
from gateway.guardrail.application.service.inspector import Inspector
from gateway.guardrail.application.service.model_tier import FailMode, ModelTier
from gateway.guardrail.domain.models.execution_plan import ModelNodeSpec
from gateway.guardrail.domain.models.guardrail import Guardrail, VerdictAction
from gateway.guardrail.domain.models.mode import Mode
from gateway.proxy.application.authenticated_request import AuthenticatedRequest
from gateway.proxy.application.port.llm_upstream import UpstreamResult
from gateway.proxy.application.port.upstream_resolver import Upstream
from gateway.proxy.application.service.proxy_service import ProxyService


class FakeModelJudge:
    def __init__(self, results: Sequence[JudgeResult]) -> None:
        self.results = tuple(results)
        self.calls: list[tuple[JudgeRequest, ...]] = []

    async def judge(self, requests: Sequence[JudgeRequest]) -> Sequence[JudgeResult]:
        self.calls.append(tuple(requests))
        return self.results


class FakePlans:
    def __init__(self, plan) -> None:
        self.plan = plan

    def get(self, guardrail: str):
        return self.plan if guardrail == self.plan.guardrail else None


class FakeUpstream:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []
        self.stream_payloads: list[bytes] = []

    async def complete(
        self, *, base_url: str, api_key: str, path: str, payload: bytes
    ) -> UpstreamResult:
        self.payloads.append(payload)
        return UpstreamResult(
            status_code=200,
            headers={"content-type": "application/json"},
            body=orjson.dumps(
                {
                    "model": "chat-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            ),
            elapsed_s=0.0,
        )

    @asynccontextmanager
    async def open_stream(
        self, *, base_url: str, api_key: str, path: str, payload: bytes
    ) -> AsyncIterator[FakeUpstreamStream]:
        self.stream_payloads.append(payload)
        yield FakeUpstreamStream()


class FakeUpstreamStream:
    status_code = 200
    headers = {"content-type": "text/event-stream"}

    async def aiter(self) -> AsyncIterator[bytes]:
        if False:
            yield b""


class FakeResolver:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def resolve(self, model: str) -> Upstream:
        self.models.append(model)
        return Upstream(base_url="http://upstream", api_key="secret")


class FakeAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def submit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _plan(*, action: str = "block", hint: bool = False):
    nodes = [
        {"id": "extract", "type": "extract", "config": {"checkpoint": "input"}},
        {
            "id": "model",
            "type": "model",
            "config": {
                "checkpoint": "input",
                "policy": "Does this user input contain a secret?",
            },
        },
        {"id": "verdict", "type": "verdict", "config": {"action": action}},
    ]
    if hint:
        nodes.extend(
            [
                {"id": "regex", "type": "regex", "config": {"pattern": "secret"}},
                {"id": "all", "type": "all", "config": {}},
            ]
        )
        edges = [
            ("extract", "regex"),
            ("extract", "model"),
            ("regex", "all"),
            ("model", "all"),
            ("all", "verdict"),
        ]
    else:
        edges = [("extract", "model"), ("model", "verdict")]
    guardrail = Guardrail.draft(
        name="model-tier",
        description="",
        graph={
            "nodes": nodes,
            "edges": [{"src": src, "dst": dst} for src, dst in edges],
        },
    )
    guardrail.validate()
    return compile_guardrail(guardrail)


def _inspection() -> Inspection:
    return Inspection(
        action=VerdictAction.ALLOW,
        tier=TIER_RULES,
        pending_model=("verdict",),
    )


def _model_tier(judge: FakeModelJudge, *, fail_mode: FailMode = FailMode.CLOSED) -> ModelTier:
    return ModelTier(
        model_judge=judge,
        model="mistralai/Shieldstral-1.0-3B@revision",
        deadline_ms=250,
        fail_modes={"input": fail_mode},
    )


def _judge_result(*, violated: bool | None, score: float | None = 0.8) -> JudgeResult:
    return JudgeResult(
        node_id="model",
        violated=violated,
        score=score,
        raw_label="yes" if violated else "no" if violated is False else "timeout",
    )


async def test_violated_model_verdict_applies_declared_action() -> None:
    """위반이면 verdict 선언 action을 적용하고 model tier로 기록한다."""
    judge = FakeModelJudge([_judge_result(violated=True)])
    result = await _model_tier(judge).evaluate(
        inspection=_inspection(),
        plan=_plan(),
        text="contains a secret",
        mode=Mode.ENFORCE,
    )

    assert result.action is VerdictAction.BLOCK
    assert result.tier == TIER_MODEL
    assert result.checks_fired == ("verdict",)
    assert result.pending_model == ()
    assert result.model == "mistralai/Shieldstral-1.0-3B@revision"
    assert judge.calls[0][0] == JudgeRequest(
        checkpoint="input",
        node_id="model",
        policy="Does this user input contain a secret?",
        text="contains a secret",
        strictness="strict",
        deadline_ms=250,
    )


async def test_non_violated_model_verdict_allows() -> None:
    """비위반이면 pending을 해소하고 allow를 유지한다."""
    result = await _model_tier(FakeModelJudge([_judge_result(violated=False)])).evaluate(
        inspection=_inspection(),
        plan=_plan(),
        text="ordinary request",
        mode=Mode.ENFORCE,
    )

    assert result.action is VerdictAction.ALLOW
    assert result.tier == TIER_MODEL
    assert result.checks_fired == ()
    assert result.pending_model == ()


async def test_failed_judgement_uses_enabled_fail_mode() -> None:
    """enabled 판정 실패만 체크포인트 fail-mode를 적용한다."""
    closed = await _model_tier(FakeModelJudge([_judge_result(violated=None, score=None)])).evaluate(
        inspection=_inspection(),
        plan=_plan(),
        text="ordinary request",
        mode=Mode.ENFORCE,
    )
    opened = await _model_tier(
        FakeModelJudge([_judge_result(violated=None, score=None)]),
        fail_mode=FailMode.OPEN,
    ).evaluate(
        inspection=_inspection(),
        plan=_plan(),
        text="ordinary request",
        mode=Mode.ENFORCE,
    )

    assert closed.action is VerdictAction.BLOCK
    assert opened.action is VerdictAction.ALLOW
    assert closed.model_judgements[0]["violated"] is None


async def test_model_mask_without_rule_span_becomes_block() -> None:
    """모델-only MASK는 위치를 모르므로 block으로 승격한다."""
    result = await _model_tier(FakeModelJudge([_judge_result(violated=True)])).evaluate(
        inspection=_inspection(),
        plan=_plan(action="mask"),
        text="contains a secret",
        mode=Mode.ENFORCE,
    )

    assert result.action is VerdictAction.BLOCK
    assert result.masked is False
    assert result.model_judgements[0]["applied_action"] == "block"


async def test_model_mask_with_rule_span_is_maskable() -> None:
    """힌트 규칙이 찾은 정확한 span이 있으면 모델 MASK를 허용한다."""
    result = await _model_tier(FakeModelJudge([_judge_result(violated=True)])).evaluate(
        inspection=_inspection(),
        plan=_plan(action="mask", hint=True),
        text="contains a secret",
        mode=Mode.ENFORCE,
    )

    assert result.action is VerdictAction.ALLOW
    assert result.masked is True


async def test_model_actions_merge_block_over_mask_over_allow() -> None:
    """여러 모델 verdict는 선언 순서와 무관하게 block>mask>allow로 병합한다."""
    plan = _plan(action="mask", hint=True)
    plan = replace(
        plan,
        model_nodes={
            **plan.model_nodes,
            "allow-verdict": ModelNodeSpec(
                node_id="allow-model",
                checkpoint="input",
                policy="Is this allowed?",
                action=VerdictAction.ALLOW,
                strictness="balanced",
                model_route="shieldstral",
            ),
            "block-verdict": ModelNodeSpec(
                node_id="block-model",
                checkpoint="input",
                policy="Should this be blocked?",
                action=VerdictAction.BLOCK,
                strictness="balanced",
                model_route="shieldstral",
            ),
        },
    )
    judge = FakeModelJudge(
        [
            _judge_result(violated=True),
            JudgeResult("allow-model", True, 0.8, "yes"),
            JudgeResult("block-model", True, 0.8, "yes"),
        ]
    )
    inspection = replace(_inspection(), pending_model=("verdict", "allow-verdict", "block-verdict"))

    result = await _model_tier(judge).evaluate(
        inspection=inspection,
        plan=plan,
        text="contains a secret",
        mode=Mode.ENFORCE,
    )

    assert result.action is VerdictAction.BLOCK
    assert result.checks_fired == ("verdict", "allow-verdict", "block-verdict")
    assert len(judge.calls[0]) == 3


async def test_dry_run_records_model_would_have_without_applying() -> None:
    """dry-run은 모델 차단을 적용하지 않고 would_have에 기록한다."""
    result = await _model_tier(FakeModelJudge([_judge_result(violated=True)])).evaluate(
        inspection=_inspection(),
        plan=_plan(),
        text="contains a secret",
        mode=Mode.DRY_RUN,
    )

    assert result.action is VerdictAction.ALLOW
    assert result.would_have is VerdictAction.BLOCK
    assert result.tier == TIER_MODEL


async def test_no_pending_verdict_does_not_call_model() -> None:
    """규칙-only 결과는 모델 포트를 호출하지 않는다."""
    judge = FakeModelJudge([])
    inspection = Inspection(action=VerdictAction.ALLOW, tier=TIER_RULES)
    result = await _model_tier(judge).evaluate(
        inspection=inspection,
        plan=_plan(),
        text="ordinary request",
        mode=Mode.ENFORCE,
    )

    assert result is inspection
    assert judge.calls == []


async def test_disabled_proxy_preserves_pending_and_allows_with_rules_audit(caplog) -> None:
    """기본 disabled는 pending을 감사하고 기존처럼 업스트림으로 통과시킨다."""
    plan = _plan()
    upstream = FakeUpstream()
    audit = FakeAuditSink()
    proxy = ProxyService(
        upstream=upstream,
        upstream_resolver=FakeResolver(),
        audit=audit,
        model_tier=None,
        store_bodies=False,
        audit_excerpt_max_chars=256,
        inspector=Inspector(plans=FakePlans(plan)),
    )

    result = await proxy.complete(
        auth=AuthenticatedRequest(uuid4(), "app", "model-tier"),
        mode=Mode.ENFORCE,
        payload=orjson.dumps(
            {"model": "chat-model", "messages": [{"role": "user", "content": "secret"}]}
        ),
        request_id="request",
    )

    assert result.status_code == 200
    assert len(upstream.payloads) == 1
    assert audit.events[0].tier_reached == TIER_RULES
    assert orjson.loads(audit.events[0].verdicts)["pending_model"] == ["verdict"]
    assert len(audit.events[0].content_fingerprint) == 64
    assert audit.events[0].input_body == ""
    assert audit.events[0].output_body == ""
    assert audit.events[0].tool_calls_body == ""
    assert "model tier is disabled" in caplog.text


async def test_enabled_failure_blocks_before_upstream_and_audits_model() -> None:
    """enabled input 판정 실패는 기본 fail-closed로 업스트림 전에 막는다."""
    plan = _plan()
    upstream = FakeUpstream()
    audit = FakeAuditSink()
    proxy = ProxyService(
        upstream=upstream,
        upstream_resolver=FakeResolver(),
        audit=audit,
        model_tier=_model_tier(FakeModelJudge([_judge_result(violated=None, score=None)])),
        store_bodies=False,
        audit_excerpt_max_chars=256,
        inspector=Inspector(plans=FakePlans(plan)),
    )

    result = await proxy.complete(
        auth=AuthenticatedRequest(uuid4(), "app", "model-tier"),
        mode=Mode.ENFORCE,
        payload=orjson.dumps(
            {"model": "chat-model", "messages": [{"role": "user", "content": "secret"}]}
        ),
        request_id="request",
    )

    assert result.status_code == 400
    assert upstream.payloads == []
    assert audit.events[0].tier_reached == TIER_MODEL
    assert audit.events[0].model == "mistralai/Shieldstral-1.0-3B@revision"
    assert orjson.loads(audit.events[0].verdicts)["model_judgements"][0]["violated"] is None


async def test_all_proxy_paths_share_model_input_block_before_upstream() -> None:
    """complete·test·stream 모두 같은 모델 input 차단을 업스트림 전에 적용한다."""
    plan = _plan()
    judge = FakeModelJudge([_judge_result(violated=True)])
    upstream = FakeUpstream()
    resolver = FakeResolver()
    audit = FakeAuditSink()
    proxy = ProxyService(
        upstream=upstream,
        upstream_resolver=resolver,
        audit=audit,
        model_tier=_model_tier(judge),
        store_bodies=False,
        audit_excerpt_max_chars=256,
        inspector=Inspector(plans=FakePlans(plan)),
    )
    auth = AuthenticatedRequest(uuid4(), "app", "model-tier")
    payload = orjson.dumps(
        {"model": "chat-model", "messages": [{"role": "user", "content": "secret"}]}
    )
    stream_payload = orjson.dumps(
        {
            "model": "chat-model",
            "messages": [{"role": "user", "content": "secret"}],
            "stream": True,
        }
    )

    complete_result = await proxy.complete(
        auth=auth,
        mode=Mode.ENFORCE,
        payload=payload,
        request_id="complete",
    )
    test_result = await proxy.test(plan=plan, mode=Mode.ENFORCE, payload=payload)
    async with proxy.stream(
        auth=auth,
        mode=Mode.ENFORCE,
        payload=stream_payload,
        request_id="stream",
    ) as stream_result:
        stream_body = b"".join([chunk async for chunk in stream_result.aiter()])
    async with proxy.test_stream(
        plan=plan,
        mode=Mode.ENFORCE,
        payload=stream_payload,
    ) as test_stream_result:
        test_stream_body = b"".join([chunk async for chunk in test_stream_result.aiter()])
        test_stream_pre = test_stream_result.pre()
        test_stream_completion = test_stream_result.result()

    inspections = (
        test_result.input,
        test_stream_pre.input,
        test_stream_completion.input,
    )
    assert all(inspection.blocked for inspection in inspections)
    assert all(inspection.tier == TIER_MODEL for inspection in inspections)
    assert all(inspection.pending_model == () for inspection in inspections)
    assert complete_result.status_code == 400
    assert stream_result.status_code == 400
    assert orjson.loads(stream_body)["error"]["code"] == "content_filter"
    assert test_stream_body == b""
    assert len(judge.calls) == 4
    assert all(call[0].text == "secret" for call in judge.calls)
    assert upstream.payloads == []
    assert upstream.stream_payloads == []
    assert resolver.models == []
    assert [event.tier_reached for event in audit.events] == [TIER_MODEL, TIER_MODEL]
    assert all(event.model == "mistralai/Shieldstral-1.0-3B@revision" for event in audit.events)


async def test_streaming_model_input_preserves_dry_run_would_have() -> None:
    """스트리밍 dry-run은 모델 차단을 would_have로 남기고 업스트림을 연다."""
    plan = _plan()
    judge = FakeModelJudge([_judge_result(violated=True)])
    upstream = FakeUpstream()
    audit = FakeAuditSink()
    proxy = ProxyService(
        upstream=upstream,
        upstream_resolver=FakeResolver(),
        audit=audit,
        model_tier=_model_tier(judge),
        store_bodies=False,
        audit_excerpt_max_chars=256,
        inspector=Inspector(plans=FakePlans(plan)),
    )
    auth = AuthenticatedRequest(uuid4(), "app", "model-tier")
    payload = orjson.dumps(
        {
            "model": "chat-model",
            "messages": [{"role": "user", "content": "secret"}],
            "stream": True,
        }
    )

    async with proxy.test_stream(plan=plan, mode=Mode.DRY_RUN, payload=payload) as test_stream:
        inspection = test_stream.pre().input
        assert inspection.blocked is False
        assert inspection.would_have is VerdictAction.BLOCK
        assert inspection.tier == TIER_MODEL
    async with proxy.stream(
        auth=auth,
        mode=Mode.DRY_RUN,
        payload=payload,
        request_id="stream-dry-run",
    ) as stream:
        assert stream.status_code == 200
        assert stream.headers["X-Gardevoir-Action"] == "allow"

    assert len(judge.calls) == 2
    assert len(upstream.stream_payloads) == 2
    assert audit.events[0].tier_reached == TIER_MODEL
    assert audit.events[0].action == "allow"
    assert orjson.loads(audit.events[0].verdicts)["would_have"] == "block"


async def test_disabled_streaming_preserves_pending_and_passes_upstream(caplog) -> None:
    """모델 티어 disabled 스트리밍은 pending을 보존하고 기존처럼 통과한다."""
    plan = _plan()
    upstream = FakeUpstream()
    audit = FakeAuditSink()
    proxy = ProxyService(
        upstream=upstream,
        upstream_resolver=FakeResolver(),
        audit=audit,
        model_tier=None,
        store_bodies=False,
        audit_excerpt_max_chars=256,
        inspector=Inspector(plans=FakePlans(plan)),
    )
    auth = AuthenticatedRequest(uuid4(), "app", "model-tier")
    payload = orjson.dumps(
        {
            "model": "chat-model",
            "messages": [{"role": "user", "content": "secret"}],
            "stream": True,
        }
    )

    async with proxy.test_stream(plan=plan, mode=Mode.ENFORCE, payload=payload) as test_stream:
        inspection = test_stream.pre().input
        assert inspection.blocked is False
        assert inspection.pending_model == ("verdict",)
        assert inspection.tier == TIER_RULES
    async with proxy.stream(
        auth=auth,
        mode=Mode.ENFORCE,
        payload=payload,
        request_id="stream-disabled",
    ) as stream:
        assert stream.status_code == 200

    assert len(upstream.stream_payloads) == 2
    assert audit.events[0].tier_reached == TIER_RULES
    assert orjson.loads(audit.events[0].verdicts)["pending_model"] == ["verdict"]
    assert "model tier is disabled" in caplog.text


async def test_model_mask_is_applied_before_upstream() -> None:
    """모델 MASK의 규칙 span은 non-stream input 본문에 실제 적용된다."""
    plan = _plan(action="mask", hint=True)
    upstream = FakeUpstream()
    audit = FakeAuditSink()
    proxy = ProxyService(
        upstream=upstream,
        upstream_resolver=FakeResolver(),
        audit=audit,
        model_tier=_model_tier(FakeModelJudge([_judge_result(violated=True)])),
        store_bodies=True,
        audit_excerpt_max_chars=256,
        inspector=Inspector(plans=FakePlans(plan)),
    )

    result = await proxy.complete(
        auth=AuthenticatedRequest(uuid4(), "app", "model-tier"),
        mode=Mode.ENFORCE,
        payload=orjson.dumps(
            {"model": "chat-model", "messages": [{"role": "user", "content": "a secret"}]}
        ),
        request_id="request",
    )

    assert result.status_code == 200
    sent = orjson.loads(upstream.payloads[0])
    assert sent["messages"][0]["content"] == "a [개인정보 삭제됨]"
    event = audit.events[0]
    assert "secret" not in event.excerpt
    assert "[개인정보 삭제됨]" in event.excerpt
    assert orjson.loads(event.input_body)["messages"][0]["content"] == "a secret"
    assert orjson.loads(event.output_body)["choices"][0]["message"]["content"] == "ok"
    assert orjson.loads(event.tool_calls_body) == []
