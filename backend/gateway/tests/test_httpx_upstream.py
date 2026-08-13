import asyncio

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
            base_url=UPSTREAM,
            api_key="sk-upstream",
            path="/chat/completions",
            payload=b"{}",
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
            base_url=f"{UPSTREAM}/",
            api_key="sk-x",
            path="/chat/completions",
            payload=b"{}",
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

    async def slow(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={})

    respx.post(f"{UPSTREAM}/chat/completions").mock(side_effect=slow)
    async with httpx.AsyncClient() as client:
        result = await HttpxUpstream(client, timeout_s=5.0).complete(
            base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
        )
    assert result.elapsed_s >= 0.04


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
        return_value=httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})
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
            200,
            content=_sse("a", "b", "[DONE]"),
            headers={"content-type": "text/event-stream"},
        )
    )
    async with httpx.AsyncClient() as client:
        upstream = HttpxUpstream(client, timeout_s=5.0)
        captured = {}
        with pytest.raises(RuntimeError):
            async with upstream.open_stream(
                base_url=UPSTREAM, api_key="sk-x", path="/chat/completions", payload=b"{}"
            ) as stream:
                captured["response"] = stream._response
                async for _ in stream.aiter():
                    raise RuntimeError("consumer failed")
        assert captured["response"].is_closed


@respx.mock
async def test_stream_does_not_leak_gateway_credentials():
    route = respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})
    )
    async with httpx.AsyncClient() as client:
        upstream = HttpxUpstream(client, timeout_s=5.0)
        async with upstream.open_stream(
            base_url=UPSTREAM, api_key="sk-upstream", path="/chat/completions", payload=b"{}"
        ) as stream:
            async for _ in stream.aiter():
                pass
    headers = route.calls[0].request.headers
    assert headers["authorization"] == "Bearer sk-upstream"
    assert not [k for k in headers if k.lower().startswith("x-gardevoir")]
