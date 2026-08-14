import asyncio
import datetime as dt
from contextlib import asynccontextmanager

import orjson
import pytest

from gateway.application.port.llm_upstream import UpstreamResult
from gateway.application.service.authentication_service import AuthenticatedRequest
from gateway.application.service.proxy_service import ProxyService, wants_stream
from gateway.audit.application.audit_event import AuditEvent
from gateway.contract import (
    EXTENSION_KEY,
    HEADER_ACTION,
    HEADER_AUDIT_ID,
    HEADER_GUARDRAIL,
    HEADER_GUARDRAIL_VERSION,
    HEADER_LATENCY_MS,
    HEADER_MODE,
    Mode,
)
from gateway.domain.models.api_key import ApiKey

_COMPLETION = {
    "id": "cmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "logprobs": None,
            "message": {"role": "assistant", "content": "hi"},
        }
    ],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
}


class StubUpstream:
    def __init__(
        self,
        result: UpstreamResult | None = None,
        *,
        stream_chunks: list[bytes] | None = None,
        stream_status: int = 200,
        stream_headers: dict[str, str] | None = None,
    ) -> None:
        self.result = result or UpstreamResult(
            status_code=200,
            headers={"content-type": "application/json"},
            body=orjson.dumps(_COMPLETION),
            elapsed_s=0.0,
        )
        self.stream_chunks = stream_chunks or [b"data: [DONE]\n\n"]
        self.stream_status = stream_status
        self.stream_headers = stream_headers or {"content-type": "text/event-stream"}
        self.calls: list[dict] = []
        self.closed = False

    async def complete(self, **kw) -> UpstreamResult:
        self.calls.append(kw)
        return self.result

    @asynccontextmanager
    async def open_stream(self, **kw):
        self.calls.append(kw)
        chunks = self.stream_chunks
        status = self.stream_status
        headers = self.stream_headers
        outer = self

        class _Stream:
            status_code = status

            def __init__(self) -> None:
                self.headers = dict(headers)

            async def aiter(self):
                for chunk in chunks:
                    yield chunk

        try:
            yield _Stream()
        finally:
            outer.closed = True


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def submit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _auth(mode: Mode = Mode.ENFORCE, guardrail: str = "base") -> AuthenticatedRequest:
    return AuthenticatedRequest(
        key=ApiKey(
            id="k1",
            name="app_0",
            key_hash="h",
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="sk-upstream",
            allowed_guardrails=("base",),
            default_guardrail="base",
        ),
        guardrail=guardrail,
        mode=mode,
    )


def _service(
    upstream: StubUpstream | None = None,
) -> tuple[ProxyService, StubUpstream, RecordingSink]:
    up = upstream or StubUpstream()
    sink = RecordingSink()
    return ProxyService(upstream=up, audit=sink), up, sink


# --- wants_stream ------------------------------------------------------------


def test_wants_stream_reads_the_payload():
    assert wants_stream(orjson.dumps({"stream": True})) is True
    assert wants_stream(orjson.dumps({"stream": False})) is False
    assert wants_stream(orjson.dumps({"model": "gpt-4o"})) is False


def test_wants_stream_tolerates_broken_json():
    """업스트림에 보내기 전에 우리가 먼저 터지면 안 된다."""
    assert wants_stream(b"not json at all") is False
    assert wants_stream(b"") is False
    assert wants_stream(orjson.dumps([1, 2, 3])) is False


# --- 비스트리밍 --------------------------------------------------------------


async def test_complete_relays_body_and_adds_extension():
    service, _, _ = _service()
    result = await service.complete(auth=_auth(), payload=b"{}", request_id="req_1")

    body = orjson.loads(result.body)
    assert body["choices"][0]["message"]["content"] == "hi"
    assert body[EXTENSION_KEY]["action"] == "allow"
    assert body[EXTENSION_KEY]["guardrail"] == "base"


async def test_complete_sets_contract_headers():
    service, _, _ = _service()
    result = await service.complete(auth=_auth(), payload=b"{}", request_id="req_1")

    assert result.headers[HEADER_ACTION] == "allow"
    assert result.headers[HEADER_GUARDRAIL] == "base"
    assert result.headers[HEADER_GUARDRAIL_VERSION] == "0"
    assert result.headers[HEADER_MODE] == "enforce"
    assert result.headers[HEADER_AUDIT_ID] == result.audit_id
    assert float(result.headers[HEADER_LATENCY_MS]) >= 0


async def test_audit_id_matches_header_and_body():
    service, _, _ = _service()
    result = await service.complete(auth=_auth(), payload=b"{}", request_id="req_1")
    assert orjson.loads(result.body)[EXTENSION_KEY]["audit_id"] == result.audit_id


class SlowUpstream(StubUpstream):
    """Actually waits, so total elapsed really includes the upstream time.

    스텁이 기다리지 않으면 total 이 극히 작아서 업스트림 대기를 빼든 안 빼든
    같은 결과가 나온다 — 테스트가 아무것도 검증하지 못한다.
    """

    def __init__(self, wait_s: float) -> None:
        super().__init__(
            UpstreamResult(
                status_code=200,
                headers={"content-type": "application/json"},
                body=orjson.dumps(_COMPLETION),
                elapsed_s=wait_s,
            )
        )
        self._wait_s = wait_s

    async def complete(self, **kw) -> UpstreamResult:
        await asyncio.sleep(self._wait_s)
        return await super().complete(**kw)


async def test_latency_excludes_upstream_wait():
    """게이트웨이가 추가한 지연만 보고한다 (§7.2). 비용을 숨기지 않는 것이 핵심."""
    service, _, _ = _service(SlowUpstream(0.3))
    result = await service.complete(auth=_auth(), payload=b"{}", request_id="req_1")

    reported = float(result.headers[HEADER_LATENCY_MS])
    # 업스트림이 300ms 걸렸으므로 빼지 않으면 300 이상이 나온다.
    assert reported < 50.0, f"업스트림 대기가 포함됐다 ({reported:.1f}ms)"


async def test_audit_latency_also_excludes_upstream_wait():
    """감사 로그의 지연도 같은 정의여야 한다 — 대시보드가 이 값을 집계한다."""
    service, _, sink = _service(SlowUpstream(0.3))
    await service.complete(auth=_auth(), payload=b"{}", request_id="req_1")
    assert sink.events[0].latency_ms < 50.0


async def test_audit_event_carries_usage_and_context():
    service, _, sink = _service()
    result = await service.complete(auth=_auth(), payload=b"{}", request_id="req_ctx")

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.id == result.audit_id
    assert event.request_id == "req_ctx"
    assert event.api_key_id == "k1"
    assert event.app_name == "app_0"
    assert event.guardrail == "base"
    assert event.mode == "enforce"
    assert event.action == "allow"
    assert event.model == "gpt-4o-mini"
    assert event.prompt_tokens == 11
    assert event.completion_tokens == 3


async def test_audit_created_at_is_a_datetime():
    """§11.10: unix 초를 넣으면 ClickHouse 가 1970년에 조용히 저장한다."""
    service, _, sink = _service()
    await service.complete(auth=_auth(), payload=b"{}", request_id="req_1")
    assert isinstance(sink.events[0].created_at, dt.datetime)


async def test_upstream_error_status_is_preserved():
    upstream = StubUpstream(
        UpstreamResult(
            status_code=429,
            headers={"content-type": "application/json"},
            body=orjson.dumps({"error": {"message": "slow down"}}),
            elapsed_s=0.0,
        )
    )
    service, _, _ = _service(upstream)
    result = await service.complete(auth=_auth(), payload=b"{}", request_id="req_1")
    assert result.status_code == 429
    assert orjson.loads(result.body)["error"]["message"] == "slow down"


@pytest.mark.parametrize("raw", [b"not json", b"[1,2,3]", b""])
async def test_extension_is_not_injected_into_a_non_object_body(raw):
    """업스트림이 객체가 아닌 것을 주면 원본을 그대로 중계한다."""
    upstream = StubUpstream(
        UpstreamResult(
            status_code=200, headers={"content-type": "application/json"}, body=raw, elapsed_s=0.0
        )
    )
    service, _, sink = _service(upstream)
    result = await service.complete(auth=_auth(), payload=b"{}", request_id="req_1")

    assert result.body == raw
    # 감사는 그래도 남는다
    assert len(sink.events) == 1


async def test_dry_run_is_reported_in_the_extension():
    service, _, _ = _service()
    result = await service.complete(
        auth=_auth(mode=Mode.DRY_RUN), payload=b"{}", request_id="req_1"
    )
    assert orjson.loads(result.body)[EXTENSION_KEY]["dry_run"] is True
    assert result.headers[HEADER_MODE] == "dry-run"


async def test_upstream_receives_only_upstream_credentials():
    service, upstream, _ = _service()
    await service.complete(auth=_auth(), payload=b'{"model":"gpt-4o"}', request_id="req_1")

    call = upstream.calls[0]
    assert call["api_key"] == "sk-upstream"
    assert call["base_url"] == "https://api.openai.com/v1"
    assert call["path"] == "/chat/completions"
    assert call["payload"] == b'{"model":"gpt-4o"}'


# --- 스트리밍 ----------------------------------------------------------------


async def test_stream_appends_the_extension_chunk():
    upstream = StubUpstream(
        stream_chunks=[b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n', b"data: [DONE]\n\n"]
    )
    service, _, _ = _service(upstream)

    async with service.stream(auth=_auth(), payload=b'{"stream":true}', request_id="r") as stream:
        assert stream.status_code == 200
        chunks = [c async for c in stream.aiter()]

    body = b"".join(chunks)
    assert b'"content":"hi"' in body
    assert b"[DONE]" in body
    # 마지막 청크가 확장 객체다
    last = chunks[-1]
    assert last.startswith(b"data: ")
    payload = orjson.loads(last[len(b"data: ") :].strip())
    assert payload[EXTENSION_KEY]["action"] == "allow"


async def test_stream_headers_are_available_before_the_body():
    service, _, _ = _service()
    async with service.stream(auth=_auth(), payload=b'{"stream":true}', request_id="r") as stream:
        # 본문을 읽기 전에 계약 헤더가 확정되어 있어야 한다 (§7.2)
        assert stream.headers[HEADER_ACTION] == "allow"
        assert stream.headers[HEADER_AUDIT_ID]
        assert stream.media_type == "text/event-stream"
        async for _ in stream.aiter():
            pass


async def test_stream_audit_is_submitted_after_completion():
    service, _, sink = _service()
    async with service.stream(auth=_auth(), payload=b'{"stream":true}', request_id="r") as stream:
        assert sink.events == []  # 아직 끝나지 않았다
        async for _ in stream.aiter():
            pass
    assert len(sink.events) == 1
    assert sink.events[0].request_id == "r"


async def test_stream_audit_is_submitted_even_if_the_consumer_raises():
    """소비자가 터져도 감사는 남아야 한다 — 그러지 않으면 기록에 구멍이 생긴다."""
    upstream = StubUpstream(stream_chunks=[b"a", b"b", b"data: [DONE]\n\n"])
    service, _, sink = _service(upstream)

    with pytest.raises(RuntimeError):
        async with service.stream(
            auth=_auth(), payload=b'{"stream":true}', request_id="r"
        ) as stream:
            async for _ in stream.aiter():
                raise RuntimeError("consumer failed")

    assert len(sink.events) == 1


async def test_stream_closes_the_upstream():
    service, upstream, _ = _service()
    async with service.stream(auth=_auth(), payload=b'{"stream":true}', request_id="r") as stream:
        async for _ in stream.aiter():
            pass
    assert upstream.closed is True


async def test_stream_preserves_upstream_error_status():
    upstream = StubUpstream(
        stream_status=401,
        stream_headers={"content-type": "application/json"},
        stream_chunks=[b'{"error":{"message":"bad key"}}'],
    )
    service, _, _ = _service(upstream)
    async with service.stream(auth=_auth(), payload=b'{"stream":true}', request_id="r") as stream:
        assert stream.status_code == 401
        body = b"".join([c async for c in stream.aiter()])
    assert b"bad key" in body
