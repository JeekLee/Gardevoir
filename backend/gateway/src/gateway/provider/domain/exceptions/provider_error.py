"""Provider error catalog."""

from shared_kernel.exception import (
    ConflictError,
    ErrorCatalog,
    NotFoundError,
    ValidationError,
)


class ProviderError(ErrorCatalog):
    NOT_FOUND = ("PROVIDER-001", "no such provider", NotFoundError)
    DUPLICATE_NAME = ("PROVIDER-002", "a provider with this name already exists", ConflictError)
    #: 한 모델은 정확히 한 프로바이더가 서빙한다 — 라우팅이 모호해지면 안 된다.
    MODEL_TAKEN = ("PROVIDER-003", "another provider already serves this model", ConflictError)
    NO_MODELS = ("PROVIDER-004", "a provider must serve at least one model", ValidationError)
    #: 프록시 경로 — 요청한 model 을 서빙하는 프로바이더가 없다.
    NO_PROVIDER_FOR_MODEL = (
        "PROVIDER-005",
        "no provider serves the requested model",
        NotFoundError,
    )


__all__ = ["ProviderError"]
