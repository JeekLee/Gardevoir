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
