"""httpx adapter for the upstream LLM."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from gateway.application.port.llm_upstream import HOP_BY_HOP, UpstreamResult


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
