import httpx
import orjson
import pytest
import pytest_asyncio
import respx
from openai import AsyncOpenAI

from gateway.contract import (
    EXTENSION_KEY,
    HEADER_ACTION,
    HEADER_AUDIT_ID,
    HEADER_GUARDRAIL,
    HEADER_GUARDRAIL_VERSION,
    HEADER_LATENCY_MS,
    HEADER_MODE,
)
from gateway.domain.models.api_key import generate_key, hash_key
from gateway.infrastructure.models.api_key import ApiKeyModel
from gateway.presentation.http.app import create_app
from shared_kernel.log import REQUEST_ID_HEADER

UPSTREAM = "https://api.openai.com/v1"


def _completion(content: str = "hi") -> dict:
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "logprobs": None,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }


@pytest_asyncio.fixture
async def api_key(session):
    """Persist a key and return the raw value."""
    raw = generate_key()
    session.add(
        ApiKeyModel(
            id="k-proxy",
            name="proxy-test",
            key_hash=hash_key(raw),
            upstream_base_url=UPSTREAM,
            upstream_api_key="sk-upstream",
            allowed_guardrails=["base", "doc-agent"],
            default_guardrail="base",
        )
    )
    await session.commit()
    return raw


@pytest_asyncio.fixture
async def app(engine, ch_client):
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _body(model: str = "gpt-4o", **kw) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}], **kw}


# --- 인증 --------------------------------------------------------------------


async def test_missing_authorization_is_401(client):
    r = await client.post("/v1/chat/completions", json=_body())
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "APIKEY-001"
    assert "detail" not in body


async def test_unknown_key_is_401(client):
    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"authorization": f"Bearer {generate_key()}"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "APIKEY-001"


async def test_unallowed_guardrail_is_403(client, api_key):
    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={
            "authorization": f"Bearer {api_key}",
            HEADER_GUARDRAIL: "internal-analytics",
        },
    )
    assert r.status_code == 403
    assert r.json()["code"] == "APIKEY-002"


# --- 비스트리밍 --------------------------------------------------------------


@respx.mock
async def test_relays_and_sets_contract_headers(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )
    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"authorization": f"Bearer {api_key}", REQUEST_ID_HEADER: "req-abc"},
    )

    assert r.status_code == 200
    assert r.headers[HEADER_ACTION] == "allow"
    assert r.headers[HEADER_GUARDRAIL] == "base"
    assert r.headers[HEADER_GUARDRAIL_VERSION] == "0"
    assert r.headers[HEADER_MODE] == "enforce"
    assert len(r.headers[HEADER_AUDIT_ID]) == 26
    assert float(r.headers[HEADER_LATENCY_MS]) >= 0
    assert r.headers[REQUEST_ID_HEADER] == "req-abc"

    body = orjson.loads(r.content)
    assert body["choices"][0]["message"]["content"] == "hi"
    assert body[EXTENSION_KEY]["action"] == "allow"
    assert body[EXTENSION_KEY]["audit_id"] == r.headers[HEADER_AUDIT_ID]


@respx.mock
async def test_guardrail_selection_is_honoured(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )
    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"authorization": f"Bearer {api_key}", HEADER_GUARDRAIL: "doc-agent"},
    )
    assert r.headers[HEADER_GUARDRAIL] == "doc-agent"
    assert orjson.loads(r.content)[EXTENSION_KEY]["guardrail"] == "doc-agent"


@respx.mock
async def test_dry_run_is_echoed_in_header_and_body(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )
    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"authorization": f"Bearer {api_key}", HEADER_MODE: "dry-run"},
    )
    assert r.headers[HEADER_MODE] == "dry-run"
    assert orjson.loads(r.content)[EXTENSION_KEY]["dry_run"] is True


@respx.mock
async def test_upstream_error_status_is_preserved(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )
    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"authorization": f"Bearer {api_key}"},
    )
    assert r.status_code == 429
    assert orjson.loads(r.content)["error"]["message"] == "slow down"


@respx.mock
async def test_upstream_receives_the_upstream_key_not_ours(client, api_key, audit_table):
    route = respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )
    await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"authorization": f"Bearer {api_key}"},
    )
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer sk-upstream"
    assert api_key not in str(sent.headers)


# --- 스트리밍 ----------------------------------------------------------------


def _sse(*chunks: str) -> bytes:
    return "".join(f"data: {c}\n\n" for c in chunks).encode()


@respx.mock
async def test_streaming_relays_sse_and_appends_extension(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=_sse('{"choices":[{"delta":{"content":"hi"}}]}', "[DONE]"),
            headers={"content-type": "text/event-stream"},
        )
    )
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json=_body(stream=True),
        headers={"authorization": f"Bearer {api_key}"},
    ) as r:
        assert r.status_code == 200
        # 스트리밍에서 Action 은 입력 단계까지의 판정만 뜻한다 (§7.2)
        assert r.headers[HEADER_ACTION] == "allow"
        assert HEADER_AUDIT_ID in r.headers
        got = b"".join([c async for c in r.aiter_bytes()])

    assert b'"content":"hi"' in got
    assert b"[DONE]" in got
    # 최종 판정은 마지막 청크에 있다
    assert EXTENSION_KEY.encode() in got


@respx.mock
async def test_streaming_upstream_error_status_is_preserved(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json=_body(stream=True),
        headers={"authorization": f"Bearer {api_key}"},
    ) as r:
        assert r.status_code == 401
        body = b"".join([c async for c in r.aiter_bytes()])
    assert b"bad key" in body


# --- 감사 --------------------------------------------------------------------


@respx.mock
async def test_audit_event_lands_in_clickhouse(client, api_key, audit_table, app, ch_client):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )
    r = await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={"authorization": f"Bearer {api_key}", REQUEST_ID_HEADER: "req-audit"},
    )
    await app.state.audit_sink.stop()  # 큐를 비운다

    rows = ch_client.query(
        "SELECT id, request_id, api_key_id, app_name, guardrail, mode, action, "
        "model, prompt_tokens, completion_tokens FROM audit_events"
    ).result_rows
    assert len(rows) == 1
    assert rows[0][0] == r.headers[HEADER_AUDIT_ID]
    assert rows[0][1] == "req-audit"
    assert rows[0][2] == "k-proxy"
    assert rows[0][3] == "proxy-test"
    assert rows[0][4] == "base"
    assert rows[0][5] == "enforce"
    assert rows[0][6] == "allow"
    assert rows[0][7] == "gpt-4o"
    assert rows[0][8] == 11
    assert rows[0][9] == 3


@respx.mock
async def test_streaming_audit_lands_in_clickhouse(client, api_key, audit_table, app, ch_client):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(
            200, content=_sse("[DONE]"), headers={"content-type": "text/event-stream"}
        )
    )
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json=_body(stream=True),
        headers={"authorization": f"Bearer {api_key}"},
    ) as r:
        async for _ in r.aiter_bytes():
            pass
    await app.state.audit_sink.stop()

    count = ch_client.query("SELECT count() FROM audit_events").result_rows[0][0]
    assert count == 1


async def test_rejected_request_is_not_audited_as_allow(
    client, api_key, audit_table, app, ch_client
):
    """403 은 프록시를 타지 않으므로 allow 로 기록되어서는 안 된다."""
    await client.post(
        "/v1/chat/completions",
        json=_body(),
        headers={
            "authorization": f"Bearer {api_key}",
            HEADER_GUARDRAIL: "internal-analytics",
        },
    )
    await app.state.audit_sink.stop()

    count = ch_client.query("SELECT count() FROM audit_events WHERE action='allow'").result_rows[0][
        0
    ]
    assert count == 0


# --- Phase 1 인수 기준 -------------------------------------------------------


@respx.mock
async def test_openai_sdk_works_with_base_url_swap_only(app, api_key, audit_table):
    """앱 코드 변경은 base_url 한 줄뿐이어야 한다."""
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
    assert resp.usage.prompt_tokens == 11
    # 확장 필드가 SDK 를 통과해 노출된다 (§11.9)
    assert resp.gardevoir["action"] == "allow"
    assert resp.gardevoir["guardrail"] == "base"


@respx.mock
async def test_openai_sdk_streaming_works(app, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=_sse(
                orjson.dumps(
                    {
                        "id": "c",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "gpt-4o",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "스트리밍"},
                                "finish_reason": None,
                                "logprobs": None,
                            }
                        ],
                    }
                ).decode(),
                "[DONE]",
            ),
            headers={"content-type": "text/event-stream"},
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gardevoir") as http:
        oai = AsyncOpenAI(base_url="http://gardevoir/v1", api_key=api_key, http_client=http)
        pieces = []
        async for chunk in await oai.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
        ):
            if chunk.choices and chunk.choices[0].delta.content:
                pieces.append(chunk.choices[0].delta.content)

    assert "".join(pieces) == "스트리밍"


@respx.mock
async def test_sdk_surfaces_upstream_errors_as_its_own(app, api_key, audit_table):
    """SDK 가 우리 응답을 자기 예외 타입으로 올려야 한다 — 계약이 통한다는 증거."""
    from openai import RateLimitError

    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gardevoir") as http:
        oai = AsyncOpenAI(
            base_url="http://gardevoir/v1", api_key=api_key, http_client=http, max_retries=0
        )
        with pytest.raises(RateLimitError):
            await oai.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )
