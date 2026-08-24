"""Proxy 요청 계약 에러."""

from shared_kernel.exception import ErrorCatalog, ValidationError


class ProxyError(ErrorCatalog):
    #: 가드레일은 헤더로 반드시 지정해야 한다 (X-Gardevoir-Guardrail).
    GUARDRAIL_REQUIRED = (
        "PROXY-001",
        "the X-Gardevoir-Guardrail header is required",
        ValidationError,
    )
    #: OpenAI 요청은 model 을 담아야 한다 — 그것으로 업스트림을 라우팅한다.
    MODEL_REQUIRED = ("PROXY-002", "the request body must name a model", ValidationError)


__all__ = ["ProxyError"]
