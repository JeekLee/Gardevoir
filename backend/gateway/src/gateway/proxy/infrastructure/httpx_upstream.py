"""httpx adapter for the upstream LLM."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from gateway.proxy.application.llm_upstream import HOP_BY_HOP, UpstreamResult


def filter_response_headers(headers) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


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


class HttpxUpstream:
    """Owns its transport.

    **프로세스에 클라이언트 하나다.** 요청마다 만들면 프로바이더로 가는 TCP + TLS
    핸드셰이크를 매번 다시 하고, 원격 프로바이더의 핸드셰이크(보통 50~200 ms)가 게이트웨이
    예산(§11.8 의 0.63 ms)을 통째로 삼킨다. 공유 클라이언트가 커넥션을 데워둔다.

    클라이언트를 주입받지 않고 직접 만든다. 조립 루트가 드라이버를 알 이유가 없고,
    어댑터가 자기 전송 계층을 소유하면 여는 곳과 닫는 곳이 한 파일에 있다. 접속 대상은
    설정이 아니라 요청마다 온다(API 키 행의 base_url) — 그래서 클라이언트 자체에는
    설정할 것이 없다.
    """

    def __init__(self, *, timeout_s: float, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient()
        self._timeout_s = timeout_s

    async def aclose(self) -> None:
        """Close the shared connection pool. 조립 루트의 lifespan 이 부른다."""
        await self._client.aclose()

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
            # 소비자가 중간에 터져도 업스트림 연결을 닫는다 — 그러지 않으면
            # 커넥션이 누수된다.
            await response.aclose()
