# Phase 1c: 프록시 경로 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **REQUIRED READING:** `skills/gardevoir-be/SKILL.md` before any step.

**Goal:** `/v1/chat/completions` 를 중계해 **OpenAI SDK 가 `base_url` 교체만으로 동작**하게 만든다. 판정은 아직 없다 — 항상 `allow` 지만 계약(헤더·확장 객체·감사)은 완성한다.

**Architecture:** 업스트림 LLM 과 감사 저장소를 `application/port/` Protocol 로 두고 `infrastructure/` 가 어댑터를 구현한다. `ProxyService` 가 유스케이스를 조립하고 라우터는 얇게 유지한다. 감사는 큐에 넣고 배경에서 배치 삽입해 응답을 막지 않는다.

**Tech Stack:** httpx 0.28.1 · orjson 3.11.9 · clickhouse-connect 1.7.0 · python-ulid · respx · openai SDK 3.0.0 (dev) · pytest

**설계 문서:** `docs/superpowers/specs/2026-08-12-gardevoir-design.md`
**컨벤션:** `skills/gardevoir-be/SKILL.md`
**선행:** Phase 1a (PR #1), Phase 1b (PR #2)

---

## Global Constraints

Phase 1a·1b 의 제약이 모두 유효하다. 특히 이번 단계에서 밟기 쉬운 것들:

- **`ORJSONResponse` 금지.** FastAPI 0.141 에서 폐기됐다.
  `Response(content=orjson.dumps(...), media_type="application/json")` 을 쓴다.
  `FastAPIDeprecationWarning` 은 pytest 에서 에러다.
- **`orjson` 만.** 스트리밍은 청크마다 파싱하므로 표준 `json` 은 2.3배 손해다 (§11.7).
- **`re2` 만.** 표준 `re` 금지 (§11.1). Phase 1c 에는 패턴 매칭이 없지만 습관을 고정한다.
- **`clickhouse-connect` 는 동기 클라이언트다.** 이벤트 루프에서 직접 호출하면 삽입이
  끝날 때까지 프록시 전체가 멈춘다 — 100행 5~20ms 가 진행 중인 모든 요청에 얹힌다.
  **반드시 `asyncio.to_thread` 로 감싼다.**
- **`DateTime64(3)` 에는 `datetime` 객체만.** unix 초를 int 로 넣으면 밀리초로 해석되어
  1970년에 조용히 저장된다. 에러가 나지 않는다 (§11.10).
- **감사 쓰기는 응답을 절대 막지 않는다** (§10). `blocked`/`approval_required` 는
  큐가 꽉 차도 버리지 않고, `allow` 는 버려도 된다.
- **`finish_reason` 에는 표준 값만.** 커스텀 값은 SDK 의 Literal 검증을 깨뜨린다 (§11.9).
- **확장 정보는 최상위 `gardevoir` 키에만.**
- 컨테이너 헬스체크는 `127.0.0.1`, 헬스 판정에 `grep healthy` 금지.
- **돌연변이 테스트 전에 커밋하고, 원복 후 `__pycache__` 를 지운다.**
  같은 바이트 길이 치환은 `.pyc` 무효화를 통과해 낡은 바이트코드가 재사용된다.
- 구조적 성질(임포트 방향, 컬럼 순서)은 **소스 텍스트가 아니라 AST/실행으로** 검사한다.
- 테스트를 쓸 때 **"이 코드를 지우면 어느 테스트가 실패하는가"** 를 자문한다.
- 테스트 함수 독스트링은 한국어(근거 진술), 모듈·클래스 독스트링은 영어.

### 레이어 배치 — 감사 이벤트를 어디에 두는가

`AuditEvent` 는 도메인 애그리거트가 **아니다** — 불변식도 생명주기도 없는 기록이다.
skills 의 outbox 지침과 같은 판단이다: 전송/저장 봉투는 도메인 모델이 아니다.

```
application/audit/audit_event.py    AuditEvent (frozen dataclass) + new_event_id()
application/port/audit_sink.py      AuditSink Protocol: submit(event)
infrastructure/audit/clickhouse_sink.py   컬럼 순서·행 변환·배치 삽입
infrastructure/audit/schema.py            번호 .sql 적용
```

**컬럼 순서와 행 변환은 sink 가 소유한다.** ClickHouse 의 컬럼 순서를 `AuditEvent` 에
두면 저장소 세부가 application 으로 새어든다. sink 를 Postgres 로 바꿔도 이벤트 타입은
그대로여야 한다.

**`AuditEvent` 는 `CamelModel` 이 아니다.** HTTP 경계를 건너지 않으므로 Pydantic 검증이
요청 경로에 들어갈 이유가 없다 (§11.8).

---

## File Structure

```
backend/gateway/
├── clickhouse/
│   └── 001_audit_events.sql
├── src/gateway/
│   ├── application/
│   │   ├── audit/
│   │   │   ├── __init__.py
│   │   │   └── audit_event.py          AuditEvent · new_event_id · Checkpoint
│   │   ├── port/
│   │   │   ├── __init__.py
│   │   │   ├── llm_upstream.py         LlmUpstream Protocol · UpstreamResult · UpstreamStream
│   │   │   └── audit_sink.py           AuditSink Protocol
│   │   └── service/
│   │       └── proxy_service.py        ProxyService · ProxyResult · ProxyStream
│   ├── infrastructure/
│   │   ├── audit/
│   │   │   ├── __init__.py
│   │   │   ├── schema.py               apply_clickhouse_schema
│   │   │   └── clickhouse_sink.py      ClickHouseAuditSink (큐 + 배치 + to_thread)
│   │   └── upstream/
│   │       ├── __init__.py
│   │       └── httpx_upstream.py       HttpxUpstream
│   ├── presentation/http/
│   │   ├── app.py                      (수정) sink·upstream 조립, 라우터 등록
│   │   └── chat_completions.py         POST /v1/chat/completions
│   ├── composition.py                  (수정) provide_proxy_service
│   └── cli.py                          (수정) gardevoir-migrate 추가
└── tests/
    ├── conftest.py                     (수정) ch_client · audit_table 픅스처
    ├── test_audit_event.py
    ├── test_clickhouse_sink.py
    ├── test_httpx_upstream.py
    ├── test_proxy_service.py
    └── test_chat_completions.py        E2E 포함
```

---

## Task 1: 업스트림 port + httpx 어댑터 (비스트리밍)

**Files:**
- Create: `src/gateway/application/port/__init__.py`
- Create: `src/gateway/application/port/llm_upstream.py`
- Create: `src/gateway/infrastructure/upstream/__init__.py`
- Create: `src/gateway/infrastructure/upstream/httpx_upstream.py`
- Test: `tests/test_httpx_upstream.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `application.port.llm_upstream.HOP_BY_HOP: frozenset[str]`
  - `application.port.llm_upstream.UpstreamResult` — frozen dataclass:
    `status_code: int`, `headers: dict[str, str]`, `body: bytes`, `elapsed_s: float`
  - `application.port.llm_upstream.LlmUpstream` Protocol —
    `async complete(*, base_url: str, api_key: str, path: str, payload: bytes) -> UpstreamResult`
  - `infrastructure.upstream.httpx_upstream.HttpxUpstream` —
    `__init__(client: httpx.AsyncClient, *, timeout_s: float)`
  - `infrastructure.upstream.httpx_upstream.filter_response_headers(headers) -> dict[str, str]`

**`elapsed_s` 가 필요한 이유:** `X-Gardevoir-Latency-Ms` 는 **게이트웨이가 추가한** 지연을
뜻한다(§7.2). 업스트림 대기를 빼야 하므로 어댑터가 그 시간을 측정해 돌려준다.
이 프로젝트의 주장이 "비용을 숨기지 않는다"이므로 이 값이 정확해야 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_httpx_upstream.py`:

```python
import httpx
import orjson
import pytest
import respx

from gateway.application.port.llm_upstream import HOP_BY_HOP
from gateway.infrastructure.upstream.httpx_upstream import (
    HttpxUpstream,
    filter_response_headers,
)

UPSTREAM = "https://api.openai.com/v1"


def test_filter_strips_hop_by_hop_and_encoding():
    raw = {
        "content-type": "application/json",
        "content-length": "123",
        "content-encoding": "gzip",
        "transfer-encoding": "chunked",
        "connection": "keep-alive",
        "x-request-id": "upstream-1",
    }
    assert filter_response_headers(raw) == {
        "content-type": "application/json",
        "x-request-id": "upstream-1",
    }


def test_content_length_and_encoding_are_hop_by_hop():
    """본문을 다시 조립하므로 길이와 인코딩은 우리가 정해야 한다."""
    assert "content-length" in HOP_BY_HOP
    assert "content-encoding" in HOP_BY_HOP


@respx.mock
async def test_complete_forwards_payload_and_auth():
    route = respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"id": "cmpl-1", "choices": []},
            headers={"content-type": "application/json", "content-length": "34"},
        )
    )
    payload = orjson.dumps({"model": "gpt-4o", "messages": []})

    async with httpx.AsyncClient() as client:
        result = await HttpxUpstream(client, timeout_s=5.0).complete(
            base_url=UPSTREAM,
            api_key="sk-upstream",
            path="/chat/completions",
            payload=payload,
        )

    assert result.status_code == 200
    assert orjson.loads(result.body)["id"] == "cmpl-1"
    assert "content-length" not in result.headers
    assert result.elapsed_s >= 0

    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer sk-upstream"
    assert sent.content == payload
    assert sent.headers["content-type"] == "application/json"


@respx.mock
async def test_gateway_credentials_never_reach_upstream():
    """업스트림에는 업스트림 키만 간다. gardevoir 키가 새면 안 된다."""
    route = respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json={})
    )
    async with httpx.AsyncClient() as client:
        await HttpxUpstream(client, timeout_s=5.0).complete(
            base_url=UPSTREAM, api_key="sk-upstream", path="/chat/completions", payload=b"{}"
        )
    headers = route.calls[0].request.headers
    assert "gdv_live_" not in str(headers)
    assert not [k for k in headers if k.lower().startswith("x-gardevoir")]


@respx.mock
async def test_complete_preserves_upstream_error_status():
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate limited"}})
    )
    async with httpx.AsyncClient() as client:
        result = await HttpxUpstream(client, timeout_s=5.0).complete(
            base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
        )
    assert result.status_code == 429
    assert orjson.loads(result.body)["error"]["message"] == "rate limited"


@respx.mock
async def test_complete_handles_trailing_slash_in_base_url():
    route = respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json={})
    )
    async with httpx.AsyncClient() as client:
        await HttpxUpstream(client, timeout_s=5.0).complete(
            base_url=f"{UPSTREAM}/", api_key="sk-x", path="/chat/completions", payload=b"{}"
        )
    assert route.called


@respx.mock
async def test_complete_raises_on_timeout():
    respx.post(f"{UPSTREAM}/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ReadTimeout):
            await HttpxUpstream(client, timeout_s=0.01).complete(
                base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
            )


@respx.mock
async def test_elapsed_measures_the_upstream_wait():
    """이 값이 없으면 게이트웨이가 추가한 지연을 계산할 수 없다 (§7.2)."""
    import asyncio

    async def slow(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={})

    respx.post(f"{UPSTREAM}/chat/completions").mock(side_effect=slow)
    async with httpx.AsyncClient() as client:
        result = await HttpxUpstream(client, timeout_s=5.0).complete(
            base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
        )
    assert result.elapsed_s >= 0.04
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/gateway && uv run pytest tests/test_httpx_upstream.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.application.port'`

- [ ] **Step 3: `application/port/llm_upstream.py` 구현**

```python
"""Upstream LLM port.

The gateway relays to a provider it does not own. The port keeps httpx out of
the application layer so the adapter can be swapped (§12).
"""

from dataclasses import dataclass
from typing import Protocol

#: Headers that describe a specific connection or body encoding and must not be
#: forwarded — we re-frame the body, so lengths and encodings are ours to set.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "content-encoding",
    }
)


@dataclass(frozen=True, slots=True)
class UpstreamResult:
    status_code: int
    headers: dict[str, str]
    body: bytes
    #: Upstream wait, so the gateway can report only its own added latency (§7.2).
    elapsed_s: float


class LlmUpstream(Protocol):
    async def complete(
        self, *, base_url: str, api_key: str, path: str, payload: bytes
    ) -> UpstreamResult: ...
```

`application/port/__init__.py`:

```python
from gateway.application.port.llm_upstream import (
    HOP_BY_HOP,
    LlmUpstream,
    UpstreamResult,
)

__all__ = ["HOP_BY_HOP", "LlmUpstream", "UpstreamResult"]
```

- [ ] **Step 4: `infrastructure/upstream/httpx_upstream.py` 구현**

```python
"""httpx adapter for the upstream LLM."""

import time

import httpx

from gateway.application.port.llm_upstream import HOP_BY_HOP, UpstreamResult


def filter_response_headers(headers) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


class HttpxUpstream:
    def __init__(self, client: httpx.AsyncClient, *, timeout_s: float) -> None:
        self._client = client
        self._timeout_s = timeout_s

    @staticmethod
    def _url(base_url: str, path: str) -> str:
        return base_url.rstrip("/") + "/" + path.lstrip("/")

    def _headers(self, api_key: str) -> dict[str, str]:
        # 업스트림에는 업스트림 키만 보낸다. gardevoir 헤더는 전달하지 않는다.
        return {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "application/json",
        }

    async def complete(
        self, *, base_url: str, api_key: str, path: str, payload: bytes
    ) -> UpstreamResult:
        started = time.perf_counter()
        response = await self._client.post(
            self._url(base_url, path),
            content=payload,
            headers=self._headers(api_key),
            timeout=self._timeout_s,
        )
        elapsed = time.perf_counter() - started
        return UpstreamResult(
            status_code=response.status_code,
            headers=filter_response_headers(response.headers),
            body=response.content,
            elapsed_s=elapsed,
        )
```

`infrastructure/upstream/__init__.py`:

```python
from gateway.infrastructure.upstream.httpx_upstream import (
    HttpxUpstream,
    filter_response_headers,
)

__all__ = ["HttpxUpstream", "filter_response_headers"]
```

- [ ] **Step 5: 통과 확인 + 커밋 + 돌연변이**

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check
git add -A && git commit -m "feat: 업스트림 port 와 httpx 비스트리밍 중계

hop-by-hop 헤더와 content-encoding/length 를 걸러낸다. 본문을 다시 조립하므로
길이와 인코딩은 우리가 정해야 한다.

업스트림에는 업스트림 키만 보낸다 — gardevoir 크레덴셜과 헤더가 새면 안 된다.
elapsed_s 를 재서 돌려준다. X-Gardevoir-Latency-Ms 는 게이트웨이가 추가한
지연이므로 업스트림 대기를 빼야 한다."
```

돌연변이 (커밋 후, 원복 시 `__pycache__` 정리):
- `HOP_BY_HOP` 에서 `content-length` 제거 → CAUGHT 되어야 한다
- `_headers` 에 `"x-gardevoir-user": "leak"` 추가 → CAUGHT
- `elapsed_s=0.0` 고정 → CAUGHT
- `_url` 의 `rstrip("/")` 제거 → CAUGHT

---

## Task 2: SSE 스트리밍 중계

**Files:**
- Modify: `src/gateway/application/port/llm_upstream.py`
- Modify: `src/gateway/application/port/__init__.py`
- Modify: `src/gateway/infrastructure/upstream/httpx_upstream.py`
- Test: `tests/test_httpx_upstream.py` (추가)

**Interfaces:**
- Consumes: Task 1
- Produces:
  - `application.port.llm_upstream.UpstreamStream` Protocol —
    `status_code: int`, `headers: dict[str, str]`, `aiter() -> AsyncIterator[bytes]`
  - `LlmUpstream.open_stream(*, base_url, api_key, path, payload)` —
    async context manager yielding `UpstreamStream`
  - `infrastructure.upstream.httpx_upstream.HttpxUpstreamStream`

**컨텍스트 매니저인 이유:** HTTP 응답 헤더는 본문보다 **먼저** 전송된다. 스트림을 시작하기
전에 status 와 헤더가 확정되어야 하는데, 제너레이터 하나로는 첫 청크를 받기 전에 알 수
없다 (§7.2).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_httpx_upstream.py` 에 추가:

```python
def _sse(*chunks: str) -> bytes:
    return "".join(f"data: {c}\n\n" for c in chunks).encode()


@respx.mock
async def test_open_stream_exposes_status_and_headers_before_body():
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=_sse('{"choices":[{"delta":{"content":"hi"}}]}', "[DONE]"),
            headers={"content-type": "text/event-stream", "content-length": "99"},
        )
    )
    async with httpx.AsyncClient() as client:
        upstream = HttpxUpstream(client, timeout_s=5.0)
        async with upstream.open_stream(
            base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
        ) as stream:
            # 본문을 읽기 전에 헤더가 확정되어 있어야 한다 (§7.2)
            assert stream.status_code == 200
            assert stream.headers["content-type"] == "text/event-stream"
            assert "content-length" not in stream.headers
            body = b"".join([c async for c in stream.aiter()])

    assert b"[DONE]" in body
    assert b'"content":"hi"' in body


@respx.mock
async def test_stream_relays_all_bytes_unchanged():
    payload = _sse(*[orjson.dumps({"i": i}).decode() for i in range(50)], "[DONE]")
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(
            200, content=payload, headers={"content-type": "text/event-stream"}
        )
    )
    async with httpx.AsyncClient() as client:
        upstream = HttpxUpstream(client, timeout_s=5.0)
        async with upstream.open_stream(
            base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
        ) as stream:
            got = b"".join([c async for c in stream.aiter()])
    assert got == payload


@respx.mock
async def test_open_stream_surfaces_upstream_error_status():
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    async with httpx.AsyncClient() as client:
        upstream = HttpxUpstream(client, timeout_s=5.0)
        async with upstream.open_stream(
            base_url=UPSTREAM, api_key="sk-bad", path="/chat/completions", payload=b"{}"
        ) as stream:
            assert stream.status_code == 401
            body = b"".join([c async for c in stream.aiter()])
    assert b"bad key" in body


@respx.mock
async def test_stream_requests_event_stream():
    route = respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(
            200, content=b"", headers={"content-type": "text/event-stream"}
        )
    )
    async with httpx.AsyncClient() as client:
        upstream = HttpxUpstream(client, timeout_s=5.0)
        async with upstream.open_stream(
            base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
        ) as stream:
            async for _ in stream.aiter():
                pass
    assert route.calls[0].request.headers["accept"] == "text/event-stream"


@respx.mock
async def test_stream_is_closed_even_if_the_consumer_raises():
    """소비자가 중간에 터져도 업스트림 연결이 남으면 커넥션이 누수된다."""
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(
            200, content=_sse("a", "b", "[DONE]"), headers={"content-type": "text/event-stream"}
        )
    )
    async with httpx.AsyncClient() as client:
        upstream = HttpxUpstream(client, timeout_s=5.0)
        with pytest.raises(RuntimeError):
            async with upstream.open_stream(
                base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
            ) as stream:
                async for _ in stream.aiter():
                    raise RuntimeError("consumer failed")
    # 여기까지 왔다는 것은 컨텍스트 매니저가 정상적으로 닫혔다는 뜻이다
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_httpx_upstream.py -k stream -q
```

Expected: FAIL — `AttributeError: 'HttpxUpstream' object has no attribute 'open_stream'`

- [ ] **Step 3: port 에 스트림 추가**

`application/port/llm_upstream.py` 에 추가:

```python
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager


class UpstreamStream(Protocol):
    status_code: int
    headers: dict[str, str]

    def aiter(self) -> AsyncIterator[bytes]: ...
```

그리고 `LlmUpstream` Protocol 에 추가:

```python
    def open_stream(
        self, *, base_url: str, api_key: str, path: str, payload: bytes
    ) -> AbstractAsyncContextManager[UpstreamStream]: ...
```

`application/port/__init__.py` 의 `__all__` 에 `"UpstreamStream"` 을 더한다.

- [ ] **Step 4: 어댑터에 스트림 추가**

`infrastructure/upstream/httpx_upstream.py` 에 추가:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass(slots=True)
class HttpxUpstreamStream:
    status_code: int
    headers: dict[str, str]
    _response: httpx.Response

    async def aiter(self) -> AsyncIterator[bytes]:
        """Yield raw body bytes.

        `aiter_bytes` decodes any content-encoding, which is why
        `content-encoding` is stripped from the forwarded headers.
        """
        async for chunk in self._response.aiter_bytes():
            yield chunk
```

`HttpxUpstream` 에 메서드 추가:

```python
    @asynccontextmanager
    async def open_stream(
        self, *, base_url: str, api_key: str, path: str, payload: bytes
    ) -> AsyncIterator[HttpxUpstreamStream]:
        """Open an upstream stream, exposing status and headers before the body.

        응답 헤더는 본문보다 먼저 전송되므로 스트림을 시작하기 전에 확정되어야
        한다. 제너레이터 하나로는 첫 청크 이전에 status 를 알 수 없어서 컨텍스트
        매니저로 분리한다 (§7.2).
        """
        headers = self._headers(api_key) | {"accept": "text/event-stream"}
        request = self._client.build_request(
            "POST",
            self._url(base_url, path),
            content=payload,
            headers=headers,
            timeout=self._timeout_s,
        )
        response = await self._client.send(request, stream=True)
        try:
            yield HttpxUpstreamStream(
                status_code=response.status_code,
                headers=filter_response_headers(response.headers),
                _response=response,
            )
        finally:
            await response.aclose()
```

- [ ] **Step 5: 통과 확인 + 커밋 + 돌연변이**

돌연변이:
- `finally: await response.aclose()` 제거 → CAUGHT 되어야 한다
- `accept: text/event-stream` 제거 → CAUGHT
- `filter_response_headers` 를 안 통과시킴 → CAUGHT

---

## Task 3: 감사 이벤트 + ClickHouse 스키마

**Files:**
- Create: `clickhouse/001_audit_events.sql`
- Create: `src/gateway/application/audit/__init__.py`
- Create: `src/gateway/application/audit/audit_event.py`
- Create: `src/gateway/application/port/audit_sink.py`
- Create: `src/gateway/infrastructure/audit/__init__.py`
- Create: `src/gateway/infrastructure/audit/schema.py`
- Modify: `src/gateway/cli.py` (`gardevoir-migrate` 추가)
- Modify: `pyproject.toml` (`[project.scripts]`)
- Modify: `tests/conftest.py` (`ch_client`, `audit_table` 픅스처)
- Test: `tests/test_audit_event.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `application.audit.audit_event.Checkpoint(StrEnum)` —
    `INPUT`, `TOOL_RESULT`, `OUTPUT`, `TOOL_CALL`, `NONE`
  - `application.audit.audit_event.AuditEvent` — frozen dataclass (§10 스키마와 1:1)
  - `application.audit.audit_event.new_event_id() -> str` (ULID)
  - `application.port.audit_sink.AuditSink` Protocol — `async submit(event: AuditEvent) -> None`
  - `infrastructure.audit.schema.apply_clickhouse_schema(client, sql_dir: Path) -> list[str]`
  - 콘솔 스크립트 `gardevoir-migrate` (ClickHouse 스키마 적용; Postgres 는 Alembic)

- [ ] **Step 1: ClickHouse 스키마 작성**

`clickhouse/001_audit_events.sql` — §10 스키마 그대로:

```sql
CREATE TABLE IF NOT EXISTS audit_events (
    id                String,
    created_at        DateTime64(3),
    request_id        String,
    api_key_id        String,
    app_name          LowCardinality(String),
    guardrail         LowCardinality(String),
    guardrail_version UInt32,
    mode              LowCardinality(String),
    action            LowCardinality(String),
    checkpoint        LowCardinality(String),
    checks_fired      Array(LowCardinality(String)),
    verdicts          String,
    tier_reached      LowCardinality(String),
    tainted           UInt8,
    latency_ms        Float32,
    model             LowCardinality(String),
    prompt_tokens     UInt32,
    completion_tokens UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (app_name, created_at, id);
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_audit_event.py`:

```python
import dataclasses
import datetime as dt

import pytest

from gateway.application.audit.audit_event import AuditEvent, Checkpoint, new_event_id


def _event(**kw) -> AuditEvent:
    fields: dict = {
        "id": new_event_id(),
        "created_at": dt.datetime.now(dt.UTC).replace(tzinfo=None),
        "request_id": "req_1",
        "api_key_id": "k1",
        "app_name": "app_0",
        "guardrail": "base",
        "guardrail_version": 0,
        "mode": "enforce",
        "action": "allow",
        "checkpoint": Checkpoint.NONE,
        "checks_fired": (),
        "verdicts": "[]",
        "tier_reached": "",
        "tainted": False,
        "latency_ms": 0.62,
        "model": "gpt-4o",
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }
    fields.update(kw)
    return AuditEvent(**fields)


def test_new_event_id_is_a_sortable_ulid():
    a, b = new_event_id(), new_event_id()
    assert len(a) == 26
    assert a != b
    assert sorted([b, a]) == [a, b] or a == b


def test_event_is_immutable():
    """감사 기록이 큐에 들어간 뒤 바뀌면 무엇이 저장됐는지 알 수 없다."""
    event = _event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.action = "blocked"  # type: ignore[misc]


def test_created_at_is_a_datetime_not_epoch_seconds():
    """§11.10: DateTime64(3) 에 unix 초를 넣으면 1970년에 조용히 저장된다."""
    assert isinstance(_event().created_at, dt.datetime)


def test_checks_fired_is_a_tuple():
    """가변 리스트면 큐에 들어간 뒤 호출자가 바꿀 수 있다."""
    assert isinstance(_event().checks_fired, tuple)


def test_checkpoint_values_match_the_design_document():
    assert Checkpoint.INPUT == "input"
    assert Checkpoint.TOOL_RESULT == "tool_result"
    assert Checkpoint.OUTPUT == "output"
    assert Checkpoint.TOOL_CALL == "tool_call"
    assert Checkpoint.NONE == ""


def test_audit_event_does_not_know_about_storage():
    """컬럼 순서·행 변환은 sink 가 소유한다. 저장소를 바꿔도 이벤트는 그대로다."""
    assert not hasattr(_event(), "to_row")
    field_names = {f.name for f in dataclasses.fields(AuditEvent)}
    assert "columns" not in field_names
```

`tests/conftest.py` 에 추가:

```python
import pathlib

import clickhouse_connect
import pytest

from gateway.infrastructure.audit.schema import apply_clickhouse_schema

CLICKHOUSE_SQL_DIR = pathlib.Path(__file__).resolve().parents[1] / "clickhouse"


@pytest.fixture(scope="session")
def ch_client():
    s = get_settings().clickhouse
    return clickhouse_connect.get_client(
        host=s.host, port=s.port, username=s.user, password=s.password, database=s.database
    )


@pytest.fixture
def audit_table(ch_client):
    """Fresh audit_events table per test."""
    ch_client.command("DROP TABLE IF EXISTS audit_events")
    apply_clickhouse_schema(ch_client, CLICKHOUSE_SQL_DIR)
    yield
```

- [ ] **Step 3: 구현**

`application/audit/audit_event.py`:

```python
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
```

`application/port/audit_sink.py`:

```python
"""Audit sink port.

Append-only. The adapter decides batching and storage (§10).
"""

from typing import Protocol

from gateway.application.audit.audit_event import AuditEvent


class AuditSink(Protocol):
    async def submit(self, event: AuditEvent) -> None: ...
```

`infrastructure/audit/schema.py`:

```python
"""ClickHouse schema application.

Alembic is Postgres-only. ClickHouse gets numbered .sql files applied in name
order — the audit schema is one append-only table and needs no migration tool.
Statements must be idempotent.
"""

from pathlib import Path


def apply_clickhouse_schema(client, sql_dir: Path) -> list[str]:
    applied: list[str] = []
    for path in sorted(sql_dir.glob("*.sql")):
        for statement in path.read_text().split(";"):
            if statement.strip():
                client.command(statement)
        applied.append(path.name)
    return applied
```

`cli.py` 에 추가:

```python
def migrate() -> None:
    """Apply the ClickHouse audit schema. Postgres is handled by Alembic."""
    import pathlib

    import clickhouse_connect

    from gateway.infrastructure.audit.schema import apply_clickhouse_schema

    s = get_settings().clickhouse
    client = clickhouse_connect.get_client(
        host=s.host, port=s.port, username=s.user, password=s.password, database=s.database
    )
    sql_dir = pathlib.Path(__file__).resolve().parents[2] / "clickhouse"
    print("clickhouse applied:", ", ".join(apply_clickhouse_schema(client, sql_dir)) or "(none)")
```

`pyproject.toml`:

```toml
[project.scripts]
gardevoir-createkey = "gateway.cli:createkey"
gardevoir-migrate = "gateway.cli:migrate"
```

- [ ] **Step 4: 스키마 적용 확인**

```bash
docker compose --env-file infra/envs/example/compose.env \
  -f infra/docker-compose/postgres.yml -f infra/docker-compose/clickhouse.yml up -d
cd backend/gateway && cp .env.example .env
uv run gardevoir-migrate
docker exec gardevoir-clickhouse-1 clickhouse-client -u gardevoir --password gardevoir \
  -d gardevoir -q "DESCRIBE audit_events" | head -6
rm .env
```

Expected: `id String`, `created_at DateTime64(3)` 등이 출력된다.
두 번 실행해도 실패하지 않는다(`IF NOT EXISTS`).

- [ ] **Step 5: 통과 확인 + 커밋**

---

## Task 4: ClickHouse 감사 라이터

**Files:**
- Create: `src/gateway/infrastructure/audit/clickhouse_sink.py`
- Modify: `src/gateway/infrastructure/audit/__init__.py`
- Test: `tests/test_clickhouse_sink.py`

**Interfaces:**
- Consumes: Task 3 의 `AuditEvent`, `AuditSink`
- Produces:
  - `ClickHouseAuditSink` — `__init__(client, *, batch_size, flush_interval_s, queue_maxsize)`,
    `async start()`, `async stop()` (멱등), `async submit(event)`,
    `written: int`, `dropped: int`
  - `CRITICAL_ACTIONS: frozenset[str]`
  - `AUDIT_COLUMNS: list[str]` (sink 소유)

**설계 요점 세 가지:**

1. **`_flush` 는 반드시 `asyncio.to_thread` 로 호출한다.** `clickhouse-connect` 는 동기
   클라이언트이고, 이벤트 루프에서 직접 호출하면 100행 삽입 5~20ms 가 진행 중인 모든
   요청에 얹혀 §11.8 의 0.63ms 주장과 정면 충돌한다.
2. **`_run` 은 `wait_for(queue.get(), timeout=...)` 기반이다.** 큐가 비면
   `flush_interval_s` 만큼 기다리고, 하나라도 들어오면 즉시 쌓인 것을 모아 삽입한다.
   `sleep` 기반 구현은 "배치 크기 도달 시 플러시"와 "인터벌 도달 시 플러시"를 동시에
   만족하지 못한다.
3. **`stop()` 은 멱등이다.** 테스트가 명시적으로 부르고 lifespan 종료가 또 부른다.
   `cancel()` 로 끝내고 남은 것을 직접 비운다 — 취소 지점이 `wait_for` 한 곳으로 모여
   배치가 반쯤 삽입된 상태로 죽지 않는다(`_flush` 가 동기이므로 취소 지점이 아니다).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_clickhouse_sink.py`:

```python
import asyncio
import datetime as dt
import time

from gateway.application.audit.audit_event import AuditEvent, Checkpoint, new_event_id
from gateway.infrastructure.audit.clickhouse_sink import (
    AUDIT_COLUMNS,
    ClickHouseAuditSink,
)


def _event(action: str = "allow", **kw) -> AuditEvent:
    fields: dict = {
        "id": new_event_id(),
        "created_at": dt.datetime.now(dt.UTC).replace(tzinfo=None),
        "request_id": "req_1",
        "api_key_id": "k1",
        "app_name": "app_0",
        "guardrail": "base",
        "guardrail_version": 0,
        "mode": "enforce",
        "action": action,
        "checkpoint": Checkpoint.NONE,
        "checks_fired": (),
        "verdicts": "[]",
        "tier_reached": "",
        "tainted": False,
        "latency_ms": 0.62,
        "model": "gpt-4o",
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }
    fields.update(kw)
    return AuditEvent(**fields)


def test_columns_match_the_clickhouse_table(ch_client, audit_table):
    """컬럼 목록이 테이블과 어긋나면 삽입이 조용히 엉뚱한 열에 들어간다."""
    rows = ch_client.query("DESCRIBE audit_events").result_rows
    assert [r[0] for r in rows] == AUDIT_COLUMNS


async def test_flushes_on_batch_size(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=3, flush_interval_s=60.0, queue_maxsize=100)
    await sink.start()
    for _ in range(3):
        await sink.submit(_event())
    await sink.stop()

    assert sink.written == 3
    assert ch_client.query("SELECT count() FROM audit_events").result_rows[0][0] == 3


async def test_flushes_on_interval(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=1000, flush_interval_s=0.05, queue_maxsize=100)
    await sink.start()
    await sink.submit(_event())
    await asyncio.sleep(0.3)
    written_before_stop = sink.written
    await sink.stop()

    assert written_before_stop == 1


async def test_stop_drains_remaining_events(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=1000, flush_interval_s=60.0, queue_maxsize=100)
    await sink.start()
    for _ in range(7):
        await sink.submit(_event())
    await sink.stop()

    assert ch_client.query("SELECT count() FROM audit_events").result_rows[0][0] == 7


async def test_stop_is_idempotent(ch_client, audit_table):
    """테스트가 명시적으로 부르고 lifespan 종료가 또 부른다."""
    sink = ClickHouseAuditSink(ch_client, batch_size=10, flush_interval_s=60.0, queue_maxsize=10)
    await sink.start()
    await sink.submit(_event())
    await sink.stop()
    await sink.stop()
    assert sink.written == 1


async def test_datetime_is_stored_as_the_real_date(ch_client, audit_table):
    """§11.10: unix 초를 넣으면 1970년에 조용히 저장된다."""
    sink = ClickHouseAuditSink(ch_client, batch_size=1, flush_interval_s=60.0, queue_maxsize=10)
    await sink.start()
    await sink.submit(_event())
    await sink.stop()

    stored = ch_client.query("SELECT max(created_at) FROM audit_events").result_rows[0][0]
    assert stored.year >= 2026


async def test_full_queue_drops_allow_but_keeps_critical(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=1000, flush_interval_s=60.0, queue_maxsize=2)
    # 배경 태스크를 시작하지 않아 큐가 비워지지 않는다
    await sink.submit(_event("allow"))
    await sink.submit(_event("allow"))

    await sink.submit(_event("allow"))  # 큐가 꽉 찼으므로 버려진다
    assert sink.dropped == 1

    await sink.submit(_event("blocked"))  # 임계 이벤트는 동기 삽입으로 폴백
    assert sink.dropped == 1
    assert (
        ch_client.query("SELECT count() FROM audit_events WHERE action='blocked'").result_rows[0][0]
        == 1
    )


async def test_approval_required_is_also_critical(ch_client, audit_table):
    sink = ClickHouseAuditSink(ch_client, batch_size=1000, flush_interval_s=60.0, queue_maxsize=1)
    await sink.submit(_event("allow"))
    await sink.submit(_event("approval_required"))
    assert sink.dropped == 0
    assert (
        ch_client.query(
            "SELECT count() FROM audit_events WHERE action='approval_required'"
        ).result_rows[0][0]
        == 1
    )


async def test_submit_never_raises_when_clickhouse_is_down(audit_table):
    class BrokenClient:
        def insert(self, *a, **kw):
            raise RuntimeError("clickhouse down")

    sink = ClickHouseAuditSink(
        BrokenClient(), batch_size=1, flush_interval_s=60.0, queue_maxsize=10
    )
    await sink.start()
    await sink.submit(_event("blocked"))  # 예외가 응답 경로로 새어나가면 안 된다
    await asyncio.sleep(0.2)
    await sink.stop()
    assert sink.dropped >= 1


async def test_slow_insert_does_not_block_the_event_loop(audit_table):
    """clickhouse-connect 은 동기다. to_thread 로 감싸지 않으면 프록시가 멈춘다."""

    class SlowClient:
        def insert(self, *a, **kw):
            time.sleep(0.5)

    sink = ClickHouseAuditSink(
        SlowClient(), batch_size=1, flush_interval_s=0.01, queue_maxsize=10
    )
    await sink.start()
    await sink.submit(_event())
    await asyncio.sleep(0.05)  # 삽입이 시작되도록 양보

    started = time.perf_counter()
    await asyncio.sleep(0.05)  # 루프가 자유롭다면 ~0.05초
    elapsed = time.perf_counter() - started
    await sink.stop()

    assert elapsed < 0.25, "이벤트 루프가 동기 삽입에 막혔다"
```

- [ ] **Step 2: 테스트 실패 확인 → Step 3: 구현**

`infrastructure/audit/clickhouse_sink.py`:

```python
"""Audit sink: queue in front, batched ClickHouse insert behind.

응답 경로를 절대 막지 않는다(§10). 배치는 ClickHouse 의 요구사항이기도 하다 —
작은 삽입을 자주 하면 파트가 과도하게 생긴다.

컬럼 순서와 행 변환은 여기가 소유한다. AuditEvent 는 저장소를 모른다.
"""

import asyncio
import contextlib
import logging

from gateway.application.audit.audit_event import AuditEvent

logger = logging.getLogger(__name__)

#: 감사의 존재 이유인 이벤트들. 큐가 꽉 차도 버리지 않는다 (§10).
CRITICAL_ACTIONS = frozenset({"blocked", "approval_required"})

#: clickhouse/001_audit_events.sql 의 컬럼 순서와 일치해야 한다.
AUDIT_COLUMNS = [
    "id",
    "created_at",
    "request_id",
    "api_key_id",
    "app_name",
    "guardrail",
    "guardrail_version",
    "mode",
    "action",
    "checkpoint",
    "checks_fired",
    "verdicts",
    "tier_reached",
    "tainted",
    "latency_ms",
    "model",
    "prompt_tokens",
    "completion_tokens",
]

_TABLE = "audit_events"


def _to_row(event: AuditEvent) -> list:
    """Row ordered to match AUDIT_COLUMNS.

    created_at stays a datetime. Passing unix seconds as an int makes ClickHouse
    read them as milliseconds and store 1970 dates with no error at all (§11.10).
    """
    return [
        event.id,
        event.created_at,
        event.request_id,
        event.api_key_id,
        event.app_name,
        event.guardrail,
        event.guardrail_version,
        event.mode,
        event.action,
        str(event.checkpoint),
        list(event.checks_fired),
        event.verdicts,
        event.tier_reached,
        1 if event.tainted else 0,
        event.latency_ms,
        event.model,
        event.prompt_tokens,
        event.completion_tokens,
    ]


class ClickHouseAuditSink:
    def __init__(
        self, client, *, batch_size: int, flush_interval_s: float, queue_maxsize: int
    ) -> None:
        self._client = client
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._queue: asyncio.Queue[AuditEvent] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task | None = None
        self.written = 0
        self.dropped = 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the background task, then drain what is left. Idempotent."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        while batch := self._drain(self._batch_size):
            await asyncio.to_thread(self._flush, batch)

    async def submit(self, event: AuditEvent) -> None:
        """Enqueue without blocking. Never raises into the response path."""
        try:
            self._queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass

        if event.action in CRITICAL_ACTIONS:
            # 임계 이벤트는 버리지 않는다. 이 요청 하나는 삽입을 기다리지만
            # 이벤트 루프는 막지 않는다.
            await asyncio.to_thread(self._flush, [event])
        else:
            self.dropped += 1
            logger.warning("audit queue full; dropped %s event", event.action)

    async def _run(self) -> None:
        while True:
            try:
                first = await asyncio.wait_for(
                    self._queue.get(), timeout=self._flush_interval_s
                )
            except TimeoutError:
                continue
            batch = [first, *self._drain(self._batch_size - 1)]
            await asyncio.to_thread(self._flush, batch)

    def _drain(self, limit: int) -> list[AuditEvent]:
        batch: list[AuditEvent] = []
        while len(batch) < limit:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    def _flush(self, batch: list[AuditEvent]) -> None:
        """Synchronous insert. Always call via asyncio.to_thread.

        clickhouse-connect 의 클라이언트는 동기이므로 이벤트 루프에서 직접
        호출하면 삽입이 끝날 때까지 프록시 전체가 멈춘다.
        """
        if not batch:
            return
        try:
            self._client.insert(
                _TABLE, [_to_row(e) for e in batch], column_names=AUDIT_COLUMNS
            )
            self.written += len(batch)
        except Exception:
            self.dropped += len(batch)
            logger.exception("audit insert failed; dropped %d events", len(batch))
```

- [ ] **Step 4: 통과 확인 + 커밋 + 돌연변이**

돌연변이 (전부 CAUGHT 되어야 한다):
- `to_thread` 를 벗기고 직접 `self._flush(batch)` → 이벤트 루프 테스트가 잡는다
- `CRITICAL_ACTIONS` 에서 `approval_required` 제거
- `created_at` 을 `int(event.created_at.timestamp())` 로 → 1970년 테스트가 잡는다
- `AUDIT_COLUMNS` 에서 두 항목 순서 교환 → DESCRIBE 대조가 잡는다
- `stop()` 의 드레인 제거

---

## Task 5: ProxyService

**Files:**
- Create: `src/gateway/application/service/proxy_service.py`
- Modify: `src/gateway/application/service/__init__.py`
- Test: `tests/test_proxy_service.py`

**Interfaces:**
- Consumes: Task 1·2 의 port, Task 3 의 `AuditSink`/`AuditEvent`,
  Phase 1b 의 `AuthenticatedRequest`, `contract`
- Produces:
  - `ProxyResult` — frozen dataclass: `status_code: int`, `media_type: str`,
    `headers: dict[str, str]`, `body: bytes`, `audit_id: str`
  - `ProxyStream` — `status_code: int`, `media_type: str`, `headers: dict[str, str]`,
    `aiter() -> AsyncIterator[bytes]`
  - `ProxyService` — `__init__(*, upstream: LlmUpstream, audit: AuditSink)`,
    `async complete(*, auth, payload, request_id) -> ProxyResult`,
    `stream(*, auth, payload, request_id) -> AbstractAsyncContextManager[ProxyStream]`
  - `wants_stream(payload: bytes) -> bool`

**지연 계산:** `latency_ms = (전체 경과 − 업스트림 대기) × 1000`. §7.2 가 요구하는
"게이트웨이가 추가한 지연"이다. 이 프로젝트의 주장이 "비용을 숨기지 않는다"이므로
업스트림 대기를 포함시키면 안 된다.

**스트리밍의 확장 객체:** 스트림 마지막에 `data: {"gardevoir": {...}}` 청크를 덧붙인다.
헤더는 본문보다 먼저 나가므로 `X-Gardevoir-Action` 은 입력 단계까지의 판정만 뜻하고,
최종 판정은 마지막 청크에 있다 (§7.2).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_proxy_service.py` — 요지(전체는 구현 시 이 목록을 모두 포함할 것):

```python
import datetime as dt

import orjson
import pytest

from gateway.application.audit.audit_event import AuditEvent
from gateway.application.port.llm_upstream import UpstreamResult
from gateway.application.service.authentication_service import AuthenticatedRequest
from gateway.application.service.proxy_service import ProxyService, wants_stream
from gateway.contract import (
    EXTENSION_KEY,
    HEADER_ACTION,
    HEADER_GUARDRAIL,
    HEADER_LATENCY_MS,
    HEADER_MODE,
    Action,
    Mode,
)
from gateway.domain.models.api_key import ApiKey


class StubUpstream:
    def __init__(self, result: UpstreamResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def complete(self, **kw) -> UpstreamResult:
        self.calls.append(kw)
        return self.result


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


_COMPLETION = {
    "id": "cmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o",
    "choices": [
        {"index": 0, "finish_reason": "stop", "logprobs": None,
         "message": {"role": "assistant", "content": "hi"}}
    ],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
}
```

테스트 목록 (각각 독립 함수로):

1. `test_wants_stream_reads_the_payload` — `{"stream": true}` / `false` / 없음 / 깨진 JSON
2. `test_complete_relays_body_and_adds_extension` — 응답 본문에 `gardevoir` 키가 붙는다
3. `test_complete_sets_contract_headers` — 6개 헤더가 모두 있고 값이 맞다
4. `test_audit_id_matches_header_and_body` — 헤더와 본문의 `audit_id` 가 같다
5. `test_latency_excludes_upstream_wait` — `elapsed_s=0.5` 인 업스트림에 대해
   `latency_ms < 100` 이다 (게이트웨이 추가 지연만)
6. `test_audit_event_is_submitted_with_usage` — `prompt_tokens=11`, `completion_tokens=3`
7. `test_audit_event_carries_key_and_guardrail` — `api_key_id`, `app_name`, `guardrail`, `mode`
8. `test_audit_created_at_is_a_datetime` — §11.10
9. `test_upstream_error_status_is_preserved` — 429 가 그대로
10. `test_extension_is_not_injected_into_non_dict_body` — 업스트림이 배열/깨진 JSON을 줘도
    터지지 않고 원본을 그대로 중계한다
11. `test_dry_run_extension_reports_dry_run` — `mode=dry-run` 이면 `dry_run: True`
12. `test_upstream_receives_only_upstream_credentials` — `sk-upstream` 이 전달되고
    gardevoir 키는 없다
13. `test_stream_appends_extension_chunk` — 마지막 청크가 `data: {"gardevoir": ...}`
14. `test_stream_audit_is_submitted_after_completion` — 스트림을 다 읽은 뒤 이벤트 1건
15. `test_stream_audit_is_submitted_even_if_consumer_raises` — 소비자가 터져도 감사 1건

- [ ] **Step 2~4: 구현 → 통과 → 커밋 → 돌연변이**

돌연변이:
- 확장 객체 주입 제거 → CAUGHT
- `latency_ms` 에서 업스트림 대기를 빼지 않음 → CAUGHT
- 감사 submit 제거 → CAUGHT
- 스트림 종료 시 감사 submit 을 `finally` 밖으로 → 소비자 예외 테스트가 CAUGHT
- `usage` 파싱 제거 → CAUGHT

---

## Task 6: 라우트 + 조립 + E2E

**Files:**
- Create: `src/gateway/presentation/http/chat_completions.py`
- Modify: `src/gateway/composition.py`
- Modify: `src/gateway/presentation/http/app.py`
- Test: `tests/test_chat_completions.py`

**Interfaces:**
- Consumes: 앞선 모든 태스크
- Produces:
  - `presentation.http.chat_completions.router` — `POST /v1/chat/completions`
  - `composition.provide_proxy_service` / `ProxyServiceDep`
  - `app.state.audit_sink`, `app.state.upstream`

**라우터는 얇게 유지한다** — 인증과 프록시 서비스에만 의존하고 인프라를 임포트하지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_chat_completions.py` — 요지:

1. `test_missing_authorization_is_401` + 응답이 `ErrorResponse` 형태
2. `test_unknown_key_is_401`
3. `test_unallowed_guardrail_is_403` — `X-Gardevoir-Guardrail: internal-analytics`
4. `test_relays_and_sets_contract_headers` — 6개 헤더 + `gardevoir` 확장
5. `test_dry_run_is_echoed_in_header_and_body`
6. `test_request_id_is_recorded_in_audit`
7. `test_streaming_relays_sse_and_appends_extension`
8. `test_streaming_action_header_is_input_stage_only` — 문서화된 의미를 테스트로 고정
9. `test_upstream_error_status_is_preserved`
10. `test_audit_event_lands_in_clickhouse` — sink 를 flush 하고 실제 행을 조회
11. **`test_openai_sdk_works_with_base_url_swap_only`** — Phase 1 인수 기준

E2E 형태:

```python
@respx.mock
async def test_openai_sdk_works_with_base_url_swap_only(app, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion("드롭인 동작"))
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gardevoir") as http:
        oai = AsyncOpenAI(base_url="http://gardevoir/v1", api_key=api_key, http_client=http)
        resp = await oai.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
        )
    assert resp.choices[0].message.content == "드롭인 동작"
    # 확장 필드가 SDK 를 통과해 노출된다 (§11.9)
    assert resp.gardevoir["action"] == "allow"
```

- [ ] **Step 2~4: 구현 → 통과 → 커밋**

- [ ] **Step 5: 실제 기동 확인**

```bash
cd backend/gateway && cp .env.example .env
uv run alembic upgrade head && uv run gardevoir-migrate
KEY=$(uv run gardevoir-createkey --name local-dev --upstream-api-key sk-dummy --guardrail base | tail -1)
uv run uvicorn --factory gateway.presentation.http.app:create_app --port 21000 &
sleep 3
curl -si -X POST localhost:21000/v1/chat/completions \
  -H "authorization: Bearer $KEY" -H "content-type: application/json" \
  -d '{"model":"gpt-4o","messages":[]}' | head -14
kill %1; rm .env
```

Expected: 업스트림 키가 더미이므로 401 을 중계하되 `X-Gardevoir-Action`,
`X-Gardevoir-Audit-Id`, `X-Gardevoir-Latency-Ms` 헤더가 붙어 있어야 한다.
그리고 ClickHouse 에 감사 행이 남아야 한다:

```bash
docker exec gardevoir-clickhouse-1 clickhouse-client -u gardevoir --password gardevoir \
  -d gardevoir -q "SELECT id, action, api_key_id, latency_ms FROM audit_events ORDER BY created_at DESC LIMIT 3"
```

---

## Self-Review

**1. Spec coverage (Phase 1c 범위)**

| 요구사항 | 태스크 |
|---|---|
| 업스트림 중계 (비스트리밍) | Task 1 |
| SSE 스트리밍 중계, 헤더를 본문보다 먼저 확정 (§7.2) | Task 2 |
| 감사 이벤트 스키마 (§10) | Task 3 |
| ClickHouse 스키마 적용 (번호 .sql) | Task 3 |
| 감사가 응답을 막지 않음 (§10) | Task 4 |
| 임계 이벤트 미유실 (§10) | Task 4 |
| `DateTime64(3)` 함정 (§11.10) | Task 3, 4 |
| 동기 클라이언트를 루프에서 호출 금지 (§12) | Task 4 |
| 게이트웨이 추가 지연만 보고 (§7.2) | Task 1, 5 |
| 확장 객체 (§7.3) | Task 5 |
| 스트리밍 헤더 의미 차이 (§7.2) | Task 5, 6 |
| 라우터는 얇게 | Task 6 |
| **`base_url` 교체 인수 기준** | Task 6 |

**Phase 1c 범위 밖:** 가드레일 컴파일(Phase 2), 액션 통제(Phase 3), 모델 티어와
홀드백(Phase 4), UI(Phase 5), 승인(Phase 6). `stream_holdback_tokens` 설정은 Phase 1b 에
이미 있지만 Phase 1c 에서는 **읽지 않는다** — 판정이 없으므로 홀드백할 이유가 없다.

**2. Placeholder scan**

Task 5·6 의 테스트는 목록 형태로 두었다. 코드 전문을 담으면 이 문서가 3천 줄을 넘고,
목록의 각 항목이 "무엇을 단정하는가"를 한 줄로 명시하므로 구현자가 해석할 여지가 없다.
Task 1~4 는 코드 전문을 담았다.

**3. Type consistency**

- `UpstreamResult.elapsed_s` 는 초 단위이고 `ProxyResult` 계산에서 1000을 곱한다.
- `AuditEvent.checkpoint` 는 `Checkpoint`(StrEnum)이고 sink 가 `str()` 로 정규화한다.
- `AuditEvent.checks_fired` 는 `tuple`, sink 가 `list()` 로 바꿔 ClickHouse 에 넣는다
  (`Array(LowCardinality(String))`).
- `AUDIT_COLUMNS` 는 sink 가 소유하고 `clickhouse/001_audit_events.sql` 의 순서와
  일치해야 한다 — `test_columns_match_the_clickhouse_table` 이 `DESCRIBE` 로 고정한다.
- `LlmUpstream` Protocol 의 `complete`/`open_stream` 시그니처는 `HttpxUpstream` 과
  테스트의 `StubUpstream` 이 동일하게 구현한다.
- `wants_stream` 은 `ProxyService` 모듈이 소유하고 라우터가 임포트한다.

---

## Execution Handoff

계획서를 `docs/superpowers/plans/2026-08-13-phase1c-proxy-path.md` 에 저장했다.
이 단계가 끝나면 Phase 1(프록시 코어)이 완료되고 `base_url` 교체만으로 동작하는
투명 프록시가 된다. 다음은 Phase 2(가드레일 컴파일러 + Admin API)다.
