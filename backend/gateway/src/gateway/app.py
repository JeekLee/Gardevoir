"""Composition root.

**객체 그래프가 여기서 만들어진다.** lifespan 이 프로세스 수명 자원을 조립한다 — 엔진·세션
팩토리, Redis, 액세스 토큰 코덱, ClickHouse 싱크, httpx 업스트림, 업스트림 리졸버, 계획
레지스트리. 그것들이 ``app.state`` 에 놓이고, 컨텍스트별 ``composition.py`` 가 요청 하나에
맞춰 꺼내 쓴다.

그쪽을 조립 루트라고 부르지 않는 이유: 모든 함수가 ``Request`` 를 받아서 요청 없이는
실행조차 안 된다. 조립 루트는 HTTP 요청을 인자로 받지 않는다.
"""

import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from gateway import health
from gateway.audit.infrastructure.adapter.clickhouse_sink import ClickHouseAuditSink
from gateway.audit.infrastructure.schema import apply_clickhouse_schema
from gateway.guardrail.definition.presentation import guardrail_router
from gateway.guardrail.plan.application.service.registry import PlanRegistry
from gateway.guardrail.plan.infrastructure.adapter.guardrail_source import (
    SessionScopedGuardrailSource,
)
from gateway.identity.application.service.user_service import UserService
from gateway.identity.infrastructure.dao.user_dao import SqlAlchemyUserDao
from gateway.identity.infrastructure.repository.redis_refresh_session_repository import (
    RedisRefreshSessionRepository,
)
from gateway.identity.infrastructure.repository.user_repository import SqlAlchemyUserRepository
from gateway.identity.presentation import api_key_router, auth_router, user_router
from gateway.provider.presentation import provider_router
from gateway.proxy.infrastructure.adapter.httpx_upstream import HttpxUpstream
from gateway.proxy.infrastructure.adapter.provider_upstream_resolver import ProviderUpstreamResolver
from gateway.proxy.presentation import chat_router
from gateway.settings import GatewaySettings, get_settings
from shared_kernel.auth import AccessTokenCodec
from shared_kernel.clickhouse import dispose_clickhouse, get_clickhouse_client
from shared_kernel.database import SqlAlchemyUnitOfWork, dispose_engine, get_session_factory
from shared_kernel.exception import ErrorCode, error_response, register_exception_handlers
from shared_kernel.log import RequestContextMiddleware, configure_logging
from shared_kernel.redis import dispose_redis, get_redis_client

logger = logging.getLogger(__name__)

#: 계약 버전은 URL 접두어가 담당한다 (§7.2). 라우터는 자기 하위 경로만 선언하고, 접두어는
#: 마운트하는 쪽 일이다. 버전을 올릴 때 고칠 곳이 여기 하나다.
API_PREFIX = "/v1"

#: 감사 스키마 .sql 디렉터리. src/gateway/app.py -> backend/gateway/clickhouse
_CLICKHOUSE_SQL_DIR = pathlib.Path(__file__).resolve().parents[2] / "clickhouse"


def _register_framework_exception_handlers(app: FastAPI) -> None:
    """Absorb the two exceptions FastAPI handles itself.

    그러지 않으면 404/422 가 {"detail": ...} 로 새어나가 응답 계약이 둘이 된다.

    Starlette 의 HTTPException 에 등록해야 한다. 라우트 미스매치 404 는 Starlette
    라우터가 올리고, fastapi.HTTPException 은 그 하위 클래스라서 부모를 잡지 못한다.
    부모에 걸면 둘 다 잡힌다.
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


async def _bootstrap_root_user(settings: GatewaySettings, session_factory, redis) -> None:
    """사용자가 하나도 없을 때만 설정값으로 루트 계정을 만든다.

    이후 계정은 루트가 관리 API 로 만든다. 없으면 아무도 로그인할 수 없고, 로그인이
    관리 API 의 관문이므로 새 배포가 아무것도 못 하는 상태로 뜬다.
    """
    if not (settings.root_email and settings.root_password):
        return
    async with session_factory() as session:
        await UserService(
            user_repository=SqlAlchemyUserRepository(session),
            user_dao=SqlAlchemyUserDao(session),
            refresh_session_repository=RedisRefreshSessionRepository(redis),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        ).ensure_root(email=settings.root_email, password=settings.root_password)


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        factory = get_session_factory(settings.database.dsn, echo=settings.database.echo)
        app.state.settings = settings
        app.state.session_factory = factory

        # 회원·인증 (JWT 액세스 + Redis 리프레시 세션).
        app.state.redis = get_redis_client(settings.redis)
        app.state.access_tokens = AccessTokenCodec(
            secret=settings.jwt_secret, ttl=timedelta(seconds=settings.access_token_ttl_s)
        )
        app.state.refresh_ttl = timedelta(seconds=settings.refresh_token_ttl_s)
        await _bootstrap_root_user(settings, factory, app.state.redis)

        clickhouse = get_clickhouse_client(settings.clickhouse)
        app.state.clickhouse = clickhouse
        # 감사 스키마는 여기서 적용한다. CREATE TABLE IF NOT EXISTS 라 멱등이다.
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

        # 프록시 데이터 플레인: 업스트림 전송 + 요청 model 로의 라우팅.
        app.state.upstream = HttpxUpstream(timeout_s=settings.upstream_timeout_s)
        app.state.upstream_resolver = ProviderUpstreamResolver(factory)

        # 발행된 가드레일을 프로세스 메모리로 컴파일한다 (§6). 요청 경로는 이 레지스트리의
        # dict 조회로 끝난다.
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
            await app.state.plans.stop()
            await app.state.audit_sink.stop()
            await app.state.upstream.aclose()
            await dispose_redis()
            await dispose_engine()
            # clickhouse-connect 는 동기다. 닫지 않으면 HTTP 커넥션 풀이 남는다.
            dispose_clickhouse()

    # 스펙은 debug 에서만 열린다. 기본값으로 두면 /openapi.json 이 익명으로 컨트롤 플레인
    # 경로 전체를 알려준다.
    app = FastAPI(
        title="gardevoir gateway",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    # 미들웨어를 먼저 등록해 상관 ID 가 핸들러보다 바깥에 있게 한다. 미처리 예외 핸들러는
    # ServerErrorMiddleware 안에서 돌아 이 미들웨어를 못 지나므로, 상관 ID 헤더는
    # error_response 가 직접 붙인다.
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    _register_framework_exception_handlers(app)

    # health 는 접두어 없이 붙는다 — 계약이 아니라 운영용이다.
    app.include_router(health.router)
    app.include_router(chat_router.router, prefix=API_PREFIX)
    app.include_router(auth_router.router, prefix=API_PREFIX)
    app.include_router(user_router.router, prefix=API_PREFIX)
    app.include_router(api_key_router.router, prefix=API_PREFIX)
    app.include_router(guardrail_router.router, prefix=API_PREFIX)
    app.include_router(provider_router.router, prefix=API_PREFIX)
    return app
