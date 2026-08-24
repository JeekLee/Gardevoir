"""ApiKey error catalog.

One enum line per error. No class per error (skills/gardevoir-be).
"""

from shared_kernel.exception import (
    ConflictError,
    ErrorCatalog,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


class ApiKeyError(ErrorCatalog):
    INVALID_KEY = ("APIKEY-001", "the provided API key is not valid", UnauthorizedError)
    DUPLICATE_NAME = ("APIKEY-004", "an API key with this name already exists", ConflictError)
    NOT_FOUND = ("APIKEY-006", "no such API key", NotFoundError)
    #: 회수·만료를 "없는 키"와 구분한다. 키를 제시한 사람에게만 답하므로 정보 노출
    #: 위험이 없고, 운영자가 왜 거절인지 알 수 있다.
    REVOKED = ("APIKEY-008", "this API key has been revoked", UnauthorizedError)
    EXPIRED = ("APIKEY-009", "this API key has expired", UnauthorizedError)
    EXPIRY_IN_PAST = (
        "APIKEY-010",
        "an expiry must be in the future; use revoke to disable a key now",
        ValidationError,
    )
