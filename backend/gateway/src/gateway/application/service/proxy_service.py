"""Proxy use case.

인증된 요청을 업스트림으로 중계하고, 계약 헤더·확장 객체를 붙이고, 감사
이벤트를 남긴다. Phase 1 에는 판정이 없어 항상 allow 지만 계약은 완성한다 —
나중에 추가하면 배포된 앱이 깨진다 (§7).
"""

import datetime as dt
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import orjson

from gateway.application.audit.audit_event import AuditEvent, Checkpoint, new_event_id
from gateway.application.port.audit_sink import AuditSink
from gateway.application.port.llm_upstream import LlmUpstream
from gateway.application.service.authentication_service import AuthenticatedRequest
from gateway.contract import (
    EXTENSION_KEY,
    UNVERSIONED_GUARDRAIL,
    Action,
    build_extension,
    response_headers,
)

UPSTREAM_PATH = "/chat/completions"

JSON_MEDIA_TYPE = "application/json"
SSE_MEDIA_TYPE = "text/event-stream"

_SSE_PREFIX = b"data: "
_SSE_SUFFIX = b"\n\n"


def wants_stream(payload: bytes) -> bool:
    """Read the `stream` flag without failing on anything the upstream would reject."""
    body = _decode(payload)
    return bool(isinstance(body, dict) and body.get("stream"))


def _decode(payload: bytes) -> object | None:
    try:
        return orjson.loads(payload)
    except orjson.JSONDecodeError:
        return None


@dataclass(frozen=True, slots=True)
class ProxyResult:
    status_code: int
    media_type: str
    headers: dict[str, str]
    body: bytes
    audit_id: str


@dataclass(slots=True)
class ProxyStream:
    status_code: int
    media_type: str
    headers: dict[str, str]
    audit_id: str
    _chunks: AsyncIterator[bytes] = field(repr=False)

    def aiter(self) -> AsyncIterator[bytes]:
        return self._chunks


class ProxyService:
    def __init__(self, *, upstream: LlmUpstream, audit: AuditSink) -> None:
        self._upstream = upstream
        self._audit = audit

    async def complete(
        self, *, auth: AuthenticatedRequest, payload: bytes, request_id: str
    ) -> ProxyResult:
        audit_id = new_event_id()
        started = time.perf_counter()

        result = await self._upstream.complete(
            base_url=auth.key.upstream_base_url,
            api_key=auth.key.upstream_api_key,
            path=UPSTREAM_PATH,
            payload=payload,
        )

        extension = self._extension(auth, audit_id)
        body, model, prompt_tokens, completion_tokens = self._inject(result.body, extension)
        latency_ms = self._added_latency_ms(started, result.elapsed_s)

        await self._submit_audit(
            auth=auth,
            audit_id=audit_id,
            request_id=request_id,
            latency_ms=latency_ms,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        return ProxyResult(
            status_code=result.status_code,
            media_type=result.headers.get("content-type", JSON_MEDIA_TYPE),
            headers=self._headers(auth, audit_id, latency_ms),
            body=body,
            audit_id=audit_id,
        )

    @asynccontextmanager
    async def stream(
        self, *, auth: AuthenticatedRequest, payload: bytes, request_id: str
    ) -> AsyncIterator[ProxyStream]:
        """Relay SSE, appending the extension object as a final chunk.

        헤더는 본문보다 먼저 나가므로 X-Gardevoir-Action 은 입력 단계까지의 판정만
        뜻한다. 최종 판정은 마지막 청크의 gardevoir 객체에 있다 (§7.2).
        """
        audit_id = new_event_id()
        started = time.perf_counter()
        extension = self._extension(auth, audit_id)

        cm = self._upstream.open_stream(
            base_url=auth.key.upstream_base_url,
            api_key=auth.key.upstream_api_key,
            path=UPSTREAM_PATH,
            payload=payload,
        )
        async with cm as upstream_stream:
            upstream_elapsed = time.perf_counter() - started

            async def chunks() -> AsyncIterator[bytes]:
                async for chunk in upstream_stream.aiter():
                    yield chunk
                yield _SSE_PREFIX + orjson.dumps({EXTENSION_KEY: extension}) + _SSE_SUFFIX

            try:
                yield ProxyStream(
                    status_code=upstream_stream.status_code,
                    media_type=upstream_stream.headers.get("content-type", SSE_MEDIA_TYPE),
                    headers=self._headers(
                        auth, audit_id, self._added_latency_ms(started, upstream_elapsed)
                    ),
                    audit_id=audit_id,
                    _chunks=chunks(),
                )
            finally:
                # 소비자가 터져도 감사는 남아야 한다 — 그러지 않으면 기록에
                # 구멍이 생긴다. async 제너레이터의 finally 는 가비지 컬렉션
                # 시점에 돌 수 있어 신뢰할 수 없으므로 여기에 둔다.
                await self._submit_audit(
                    auth=auth,
                    audit_id=audit_id,
                    request_id=request_id,
                    latency_ms=self._added_latency_ms(started, upstream_elapsed),
                    model="",
                    prompt_tokens=0,
                    completion_tokens=0,
                )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _added_latency_ms(started: float, upstream_elapsed_s: float) -> float:
        """Gateway-added latency only — the upstream wait is not ours (§7.2)."""
        total = time.perf_counter() - started
        return max(0.0, total - upstream_elapsed_s) * 1000

    @staticmethod
    def _extension(auth: AuthenticatedRequest, audit_id: str) -> dict:
        return build_extension(
            action=Action.ALLOW,
            guardrail=auth.guardrail,
            guardrail_version=UNVERSIONED_GUARDRAIL,
            audit_id=audit_id,
            mode=auth.mode,
        )

    @staticmethod
    def _headers(auth: AuthenticatedRequest, audit_id: str, latency_ms: float) -> dict[str, str]:
        return response_headers(
            action=Action.ALLOW,
            guardrail=auth.guardrail,
            guardrail_version=UNVERSIONED_GUARDRAIL,
            mode=auth.mode,
            audit_id=audit_id,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _inject(raw: bytes, extension: dict) -> tuple[bytes, str, int, int]:
        """Attach the extension object and read usage out of the body.

        업스트림이 객체가 아닌 것을 주면 원본을 그대로 중계한다 — 우리가 먼저
        터져서 응답을 잃는 것이 더 나쁘다.
        """
        body = _decode(raw)
        if not isinstance(body, dict):
            return raw, "", 0, 0

        body[EXTENSION_KEY] = extension
        usage = body.get("usage") or {}
        model = body.get("model") or ""
        return (
            orjson.dumps(body),
            model if isinstance(model, str) else "",
            int(usage.get("prompt_tokens") or 0) if isinstance(usage, dict) else 0,
            int(usage.get("completion_tokens") or 0) if isinstance(usage, dict) else 0,
        )

    async def _submit_audit(
        self,
        *,
        auth: AuthenticatedRequest,
        audit_id: str,
        request_id: str,
        latency_ms: float,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        await self._audit.submit(
            AuditEvent(
                id=audit_id,
                created_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
                request_id=request_id,
                api_key_id=auth.key.id,
                app_name=auth.key.name,
                guardrail=auth.guardrail,
                guardrail_version=UNVERSIONED_GUARDRAIL,
                mode=str(auth.mode),
                action=str(Action.ALLOW),
                # Phase 1 에는 판정이 없다. Phase 2 부터 실제 체크포인트가 들어간다.
                checkpoint=Checkpoint.NONE,
                checks_fired=(),
                verdicts="[]",
                tier_reached="",
                tainted=False,
                latency_ms=latency_ms,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )


__all__ = [
    "JSON_MEDIA_TYPE",
    "SSE_MEDIA_TYPE",
    "UPSTREAM_PATH",
    "ProxyResult",
    "ProxyService",
    "ProxyStream",
    "wants_stream",
]
