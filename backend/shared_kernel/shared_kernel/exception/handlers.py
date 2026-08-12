"""Central exception handling. One implementation for every bounded context.

Never register a per-BC handler — the response shape is part of the contract.

``ORJSONResponse`` is deprecated as of FastAPI 0.141: FastAPI now serializes via
Pydantic when a response model is set, which does not apply to exception
handlers. We therefore build the body with ``orjson.dumps`` and return a plain
``Response``. That is also the primitive the proxy path needs, since it relays
raw upstream bytes rather than re-serialising a model.
"""

import logging

import orjson
from fastapi import FastAPI, Request
from fastapi.responses import Response

from shared_kernel.exception.base import AppError, ErrorCode
from shared_kernel.exception.schema import ErrorResponse

logger = logging.getLogger(__name__)

JSON_MEDIA_TYPE = "application/json"


def _json(body: ErrorResponse, status_code: int) -> Response:
    return Response(
        content=orjson.dumps(body.model_dump(by_alias=True, exclude_none=True)),
        status_code=status_code,
        media_type=JSON_MEDIA_TYPE,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> Response:
        logger.log(
            exc.log_level,
            "%s %s -> %s %s",
            request.method,
            request.url.path,
            exc.code,
            exc.message,
        )
        return _json(
            ErrorResponse(code=str(exc.code), message=exc.message, details=exc.details),
            exc.http_status,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> Response:
        # 예상 못 한 예외의 메시지는 내부 정보다. 로그에는 남기고 응답에는 싣지 않는다.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return _json(
            ErrorResponse(code=str(ErrorCode.INTERNAL), message="internal server error"), 500
        )
