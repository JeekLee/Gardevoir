"""트랜잭션 경계.

**서비스가 자기 쓰기를 커밋한다.** 조립 루트의 yield 정리 코드에 맡기면 FastAPI 가
응답을 보낸 뒤에 커밋하고, 그러면 draft 를 고치고 곧바로 발행하는 요청이 이전 draft 를
읽는다 — 실제 uvicorn 에서 확인했다. 이 파일은 그 경계를 고정한다.

제너레이터를 열면 반드시 finally 로 닫는다. 열린 세션이 남으면 뒷정리의 TRUNCATE 가
잠금 대기에 걸려 스위트 전체가 멈춘다 — 이 저장소에서 여러 번 겪었다.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
import sqlalchemy
from sqlalchemy.ext.asyncio import async_sessionmaker

from gateway.application.command.guardrail_command import CreateGuardrail
from gateway.composition import GuardrailServiceDep, provide_guardrail_service
from gateway.infrastructure.models.guardrail import GuardrailModel
from gateway.presentation.http.app import create_app
from shared_kernel.exception import ValidationError

EMPTY = {"nodes": [], "edges": []}
CYCLIC = {
    "nodes": [
        {"id": "a", "type": "transform", "config": {"op": "lower"}},
        {"id": "b", "type": "transform", "config": {"op": "strip"}},
    ],
    "edges": [{"src": "a", "dst": "b"}, {"src": "b", "dst": "a"}],
}


@pytest.fixture
def request_stub(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_factory=factory)))


@asynccontextmanager
async def _service(request_stub):
    """요청 하나를 흉내낸다. 단정이 실패해도 제너레이터를 닫는다."""
    agen = provide_guardrail_service(request_stub)
    try:
        yield await agen.__anext__()
    finally:
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()


async def _names(session) -> list[str]:
    rows = await session.execute(sqlalchemy.select(GuardrailModel.name))
    return sorted(rows.scalars().all())


# --- 서비스가 커밋한다 -------------------------------------------------------


async def test_a_write_is_visible_before_the_request_ends(request_stub, session):
    """draft 를 고치고 곧바로 발행하는 요청이 새 draft 를 읽어야 한다."""
    async with _service(request_stub) as service:
        await service.create(CreateGuardrail(name="kept", graph=EMPTY))
        assert await _names(session) == ["kept"], "다른 세션에서 보이지 않는다"


async def test_the_write_survives_the_request(request_stub, session):
    async with _service(request_stub) as service:
        await service.create(CreateGuardrail(name="kept", graph=EMPTY))
    assert await _names(session) == ["kept"]


async def test_a_rejected_write_persists_nothing(request_stub, session):
    """검증이 커밋보다 앞선다 — 거부된 요청은 흔적을 남기지 않는다."""
    async with _service(request_stub) as service:
        with pytest.raises(ValidationError):
            await service.create(CreateGuardrail(name="looping", graph=CYCLIC))

    assert await _names(session) == []


async def test_an_exception_after_the_service_committed_does_not_roll_back(request_stub, session):
    """서비스가 커밋한 뒤의 실패는 되돌려지지 않는다.

    조립 루트가 커밋을 갖고 있던 때와 달라진 점이므로 명시해 둔다. 지금 라우트들은
    서비스 호출이 마지막 동작이라 그 뒤에 실패할 것이 없다.
    """
    agen = provide_guardrail_service(request_stub)
    service = await agen.__anext__()
    await service.create(CreateGuardrail(name="kept", graph=EMPTY))
    with pytest.raises(RuntimeError):
        await agen.athrow(RuntimeError("route blew up"))

    assert await _names(session) == ["kept"]


async def test_each_request_gets_its_own_session(request_stub):
    """서비스 인스턴스가 다른 것은 당연하다 — 세션이 달라야 의미가 있다."""
    first_agen = provide_guardrail_service(request_stub)
    second_agen = provide_guardrail_service(request_stub)
    try:
        first = await first_agen.__anext__()
        second = await second_agen.__anext__()
        assert first._guardrails._session is not second._guardrails._session
        assert first._guardrails._session is first._dao._session, "한 요청 안에서는 같아야 한다"
    finally:
        for agen in (first_agen, second_agen):
            with pytest.raises(StopAsyncIteration):
                await agen.__anext__()


# --- FastAPI 계약 ------------------------------------------------------------


@pytest_asyncio.fixture
async def app(engine, ch_client):
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _post(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path)


async def test_a_route_that_fails_before_writing_persists_nothing(app, session):
    @app.post("/boom-before-write")
    async def boom_before_write(service: GuardrailServiceDep):
        await service.list()
        raise RuntimeError("kaboom")

    assert (await _post(app, "/boom-before-write")).status_code == 500
    assert await _names(session) == []


async def test_a_route_that_writes_then_fails_keeps_the_write(app, session):
    """위 테스트가 '아무것도 커밋되지 않는다'로 통과하는 빈 단정이 아님을 보인다."""

    @app.post("/write-then-boom")
    async def write_then_boom(service: GuardrailServiceDep):
        await service.create(CreateGuardrail(name="kept-route", graph=EMPTY))
        raise RuntimeError("kaboom")

    assert (await _post(app, "/write-then-boom")).status_code == 500
    assert await _names(session) == ["kept-route"]


async def test_a_successful_route_commits(app, session):
    @app.post("/write-then-ok")
    async def write_then_ok(service: GuardrailServiceDep):
        await service.create(CreateGuardrail(name="ok-route", graph=EMPTY))
        return {"ok": True}

    assert (await _post(app, "/write-then-ok")).status_code == 200
    assert await _names(session) == ["ok-route"]
