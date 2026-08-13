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
