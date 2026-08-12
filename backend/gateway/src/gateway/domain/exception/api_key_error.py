"""ApiKey error catalog.

One enum line per error. No class per error (skills/gardevoir-be).
"""

from shared_kernel.exception import ConflictError, ErrorCatalog, ForbiddenError, UnauthorizedError


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
