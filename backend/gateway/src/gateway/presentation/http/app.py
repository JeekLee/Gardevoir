"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from gateway.domain.models.api_key import ApiKey
from gateway.infrastructure.engine import dispose_engine, get_session_factory
from gateway.infrastructure.repository import (
    CachedApiKeyRepository,
    SqlAlchemyApiKeyRepository,
)
from gateway.presentation.http import health
from gateway.settings import GatewaySettings, get_settings
from shared_kernel.exception import ErrorCode, error_response, register_exception_handlers
from shared_kernel.log import RequestContextMiddleware, configure_logging

logger = logging.getLogger(__name__)


class SessionScopedApiKeyRepository:
    """Opens a short-lived session per operation.

    캐시가 앞에 있어 대부분의 요청은 여기까지 오지 않는다 (§6).
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        async with self._session_factory() as session:
            return await SqlAlchemyApiKeyRepository(session).find_by_hash(key_hash)

    async def add(self, key: ApiKey) -> None:
        async with self._session_factory() as session:
            await SqlAlchemyApiKeyRepository(session).add(key)
            await session.commit()


def _register_framework_exception_handlers(app: FastAPI) -> None:
    """Absorb the two exceptions FastAPI handles itself.

    그러지 않으면 404/422 가 {"detail": ...} 로 새어나가 응답 계약이 둘이 된다.

    Starlette 의 HTTPException 에 등록해야 한다. 라우트 미스매치 404 는 Starlette
    라우터가 올리고, fastapi.HTTPException 은 그 하위 클래스라서 부모를 잡지
    못한다. 부모에 걸면 둘 다 잡힌다.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        logger.log(level, "%s %s -> HTTP-%s", request.method, request.url.path, exc.status_code)
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return error_response(
            code=f"HTTP-{exc.status_code}", message=message, status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        # errors() 의 input 은 호출자 페이로드, url 은 pydantic 문서 링크다.
        # 어느 쪽도 응답에 실을 이유가 없다.
        safe = [
            {"loc": [str(part) for part in error.get("loc", ())], "msg": error.get("msg", "")}
            for error in exc.errors()
        ]
        logger.warning("%s %s -> validation failed", request.method, request.url.path)
        return error_response(
            code=str(ErrorCode.VALIDATION),
            message="request validation failed",
            details={"errors": safe},
            status_code=422,
        )


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        factory = get_session_factory(settings.database.dsn, echo=settings.database.echo)
        app.state.key_cache = CachedApiKeyRepository(
            SessionScopedApiKeyRepository(factory), ttl_s=settings.key_cache_ttl_s
        )
        try:
            yield
        finally:
            await dispose_engine()

    app = FastAPI(title="gardevoir gateway", version="0.1.0", lifespan=lifespan)

    # 미들웨어를 먼저 등록해 상관 ID 가 핸들러보다 바깥에 있게 한다. 다만 미처리
    # 예외 핸들러는 ServerErrorMiddleware 안에서 돌아 이 미들웨어를 못 지나므로,
    # 상관 ID 헤더는 error_response 가 직접 붙인다.
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    _register_framework_exception_handlers(app)

    app.include_router(health.router)
    return app
