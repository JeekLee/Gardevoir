"""Error categories.

An error's category decides its HTTP status and log level. A bounded context
never subclasses these — it adds a line to its ``ErrorCatalog`` instead.
"""

import logging
from enum import StrEnum


class ErrorCode(StrEnum):
    INTERNAL = "INTERNAL"
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"


class AppError(Exception):
    code: object = ErrorCode.INTERNAL
    http_status: int = 500
    log_level: int = logging.ERROR

    def __init__(
        self,
        message: str | None = None,
        *,
        code: object | None = None,
        details: dict | None = None,
    ) -> None:
        if code is not None:
            # 인스턴스 속성으로만 덮는다. 클래스 속성은 건드리지 않는다.
            self.code = code
        self.message = message or self.__class__.__name__
        self.details = details
        super().__init__(self.message)


class ValidationError(AppError):
    code = ErrorCode.VALIDATION
    http_status = 422
    log_level = logging.WARNING


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    http_status = 404
    log_level = logging.WARNING


class UnauthorizedError(AppError):
    code = ErrorCode.UNAUTHORIZED
    http_status = 401
    log_level = logging.WARNING


class ForbiddenError(AppError):
    code = ErrorCode.FORBIDDEN
    http_status = 403
    log_level = logging.WARNING


class ConflictError(AppError):
    code = ErrorCode.CONFLICT
    http_status = 409
    log_level = logging.WARNING
