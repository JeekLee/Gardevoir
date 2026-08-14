"""FastAPI application factory."""

import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager

import clickhouse_connect
import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from gateway import health
from gateway.audit.infrastructure import ClickHouseAuditSink
from gateway.audit.infrastructure.schema import apply_clickhouse_schema
from gateway.guardrail.definition.presentation import admin_router
from gateway.guardrail.plan.application.registry import PlanRegistry
from gateway.guardrail.plan.infrastructure import SessionScopedGuardrailSource
from gateway.identity.application.api_key_service import ApiKeyService
from gateway.identity.infrastructure import (
    CachedApiKeyRepository,
    SessionScopedApiKeyRepository,
    SqlAlchemyApiKeyDao,
    SqlAlchemyApiKeyRepository,
)
from gateway.identity.presentation import admin_router as api_key_router
from gateway.proxy.infrastructure import HttpxUpstream
from gateway.proxy.presentation import chat_router
from gateway.settings import GatewaySettings, get_settings
from shared_kernel.database import dispose_engine, get_session_factory
from shared_kernel.exception import ErrorCode, error_response, register_exception_handlers
from shared_kernel.log import RequestContextMiddleware, configure_logging

logger = logging.getLogger(__name__)

#: 감사 스키마 .sql 디렉터리. src/gateway/app.py -> backend/gateway/clickhouse
_CLICKHOUSE_SQL_DIR = pathlib.Path(__file__).resolve().parents[2] / "clickhouse"


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


async def _bootstrap_admin_key(settings: GatewaySettings, session_factory) -> None:
    """설정에 부트스트랩 키가 있고 활성 admin 키가 없으면 하나 심는다.

    없으면 아무도 관리 API 를 부를 수 없고, 키를 만드는 것이 그 관리 API 이므로 새
    배포가 아무것도 못 하는 상태로 뜬다.
    """
    if not settings.bootstrap_admin_key:
        return
    async with session_factory() as session:
        service = ApiKeyService(
            keys=SqlAlchemyApiKeyRepository(session),
            dao=SqlAlchemyApiKeyDao(session),
            transaction=session,
        )
        await service.ensure_bootstrap_admin(settings.bootstrap_admin_key)


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        factory = get_session_factory(settings.database.dsn, echo=settings.database.echo)
        # 저작 API 는 요청마다 세션을 연다. 프록시 경로는 키 캐시 덕분에 DB 를
        # 건드리지 않는다 (§6).
        app.state.settings = settings
        app.state.session_factory = factory
        app.state.key_cache = CachedApiKeyRepository(
            SessionScopedApiKeyRepository(factory), ttl_s=settings.key_cache_ttl_s
        )

        await _bootstrap_admin_key(settings, factory)

        ch = settings.clickhouse
        clickhouse = clickhouse_connect.get_client(
            host=ch.host,
            port=ch.port,
            username=ch.user,
            password=ch.password,
            database=ch.database,
        )
        app.state.clickhouse = clickhouse
        # 감사 스키마를 여기서 적용한다. CREATE TABLE IF NOT EXISTS 라 멱등이고,
        # 별도 명령으로 두면 배포 절차가 하나 늘고 빠뜨리면 첫 요청에서 터진다.
        # clickhouse-connect 는 동기라 이벤트 루프를 막지 않게 스레드로 뺀다.
        applied = await asyncio.to_thread(apply_clickhouse_schema, clickhouse, _CLICKHOUSE_SQL_DIR)
        if applied:
            logger.info("clickhouse schema applied: %s", ", ".join(applied))

        app.state.audit_sink = ClickHouseAuditSink(
            clickhouse,
            batch_size=settings.audit_batch_size,
            flush_interval_s=settings.audit_flush_interval_s,
            queue_maxsize=settings.audit_queue_maxsize,
        )
        await app.state.audit_sink.start()

        http_client = httpx.AsyncClient()
        app.state.upstream = HttpxUpstream(http_client, timeout_s=settings.upstream_timeout_s)

        # 발행된 가드레일을 프로세스 메모리로 컴파일한다 (§6). 요청 경로는 이
        # 레지스트리의 dict 조회로 끝난다.
        app.state.plans = PlanRegistry(
            source=SessionScopedGuardrailSource(factory),
            poll_interval_s=settings.plan_poll_interval_s,
        )
        loaded = await app.state.plans.load_all()
        logger.info("compiled %d guardrail plan(s) at startup", loaded)
        await app.state.plans.start()

        try:
            yield
        finally:
            # stop() 은 멱등이다 — 테스트가 명시적으로 부를 수 있다.
            await app.state.plans.stop()
            await app.state.audit_sink.stop()
            await http_client.aclose()
            await dispose_engine()

    # 스펙은 debug 에서만 열린다. 기본값으로 두면 /openapi.json 이 익명으로 컨트롤
    # 플레인 경로 전체를 알려주므로, infra/README.md 가 권하는 완화책
    # ("인그레스에서 /v1/admin/* 차단")이 그 구멍을 덮지 못한다.
    #
    # docs_url/redoc_url 을 따로 끄지 않는 이유: FastAPI 는 openapi_url 이 없으면
    # /docs 와 /redoc 라우트를 아예 등록하지 않는다. 같은 조건으로 한 번 더 쓰면
    # 반증할 수 없는 줄이 된다 — 돌연변이 테스트에서 그것이 드러났다.
    app = FastAPI(
        title="gardevoir gateway",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    # 미들웨어를 먼저 등록해 상관 ID 가 핸들러보다 바깥에 있게 한다. 다만 미처리
    # 예외 핸들러는 ServerErrorMiddleware 안에서 돌아 이 미들웨어를 못 지나므로,
    # 상관 ID 헤더는 error_response 가 직접 붙인다.
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    _register_framework_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(chat_router.router)
    # ⚠️ 사람 인증이 아직 없다 — admin 스코프 키만 요구한다. 외부에 노출하지 말 것.
    # admin_router 의 모듈 독스트링과 infra/README.md 참조.
    app.include_router(admin_router.router)
    # ⚠️ 키 발급·회수. admin 키가 새면 다른 키를 전부 만들 수 있어 더 위험하다.
    app.include_router(api_key_router.router)
    return app
