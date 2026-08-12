"""Error response body."""

from shared_kernel.api.schema import CamelModel


class ErrorResponse(CamelModel):
    code: str
    message: str
    details: dict | None = None
    request_id: str | None = None
