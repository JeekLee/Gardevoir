"""ApiKey error catalog.

One enum line per error. No class per error (skills/gardevoir-be).
"""

from shared_kernel.exception import (
    ConflictError,
    ErrorCatalog,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


class ApiKeyError(ErrorCatalog):
    INVALID_KEY = ("APIKEY-001", "the provided API key is not valid", UnauthorizedError)
    GUARDRAIL_NOT_ALLOWED = (
        "APIKEY-002",
        "the requested guardrail is not allowed for this key",
        ForbiddenError,
    )
    NO_GUARDRAIL_CONFIGURED = (
        "APIKEY-003",
        "this key has no guardrail configured",
        ForbiddenError,
    )
    DUPLICATE_NAME = ("APIKEY-004", "an API key with this name already exists", ConflictError)
    SCOPE_NOT_GRANTED = ("APIKEY-005", "this key does not have the required scope", ForbiddenError)
    NOT_FOUND = ("APIKEY-006", "no such API key", NotFoundError)
    UPSTREAM_KEY_REQUIRED = (
        "APIKEY-007",
        "a proxy-scoped key needs an upstream API key",
        ValidationError,
    )
    #: 회수·만료를 "없는 키"와 구분한다. 키를 제시한 사람에게만 답하므로 정보 노출
    #: 위험이 없고, 운영자가 왜 거절인지 알 수 있다.
    REVOKED = ("APIKEY-008", "this API key has been revoked", UnauthorizedError)
    EXPIRED = ("APIKEY-009", "this API key has expired", UnauthorizedError)
    EXPIRY_IN_PAST = (
        "APIKEY-010",
        "an expiry must be in the future; use revoke to disable a key now",
        ValidationError,
    )
