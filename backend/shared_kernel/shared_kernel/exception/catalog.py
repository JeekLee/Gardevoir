"""Per-aggregate error catalog.

Each member's value is ``(code, default_message, category)``. The member acts as
the factory for its error, so a bounded context adds one enum line per error and
never writes a class per error.
"""

from enum import Enum
from typing import NoReturn

from shared_kernel.exception.base import AppError


class ErrorCatalog(Enum):
    def __init__(self, code: str, default_message: str, category: type[AppError]) -> None:
        self.code = code
        self.default_message = default_message
        self.category = category

    def exception(self, message: str | None = None, *, details: dict | None = None) -> AppError:
        return self.category(message or self.default_message, code=self.code, details=details)

    def raise_(self, message: str | None = None, *, details: dict | None = None) -> NoReturn:
        raise self.exception(message, details=details)
