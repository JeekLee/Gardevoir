"""Correlation id middleware.

Reuses the caller's X-Request-Id when present so gateway audit rows can be
joined against the caller's own logs (§7.2), and echoes it back.
"""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from shared_kernel.log.context import REQUEST_ID_HEADER, set_request_id


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        set_request_id(request_id)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
