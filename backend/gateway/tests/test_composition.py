"""트랜잭션 경계.

라우트가 예외를 올렸을 때 절반 쓰인 상태가 커밋되지 않아야 한다. 서비스 테스트로는
드러나지 않는다 — 대부분의 실패는 검증 단계에서 나서 아직 쓴 것이 없기 때문이다.
여기서는 쓰기가 성공한 뒤에 실패를 주입해 경계 자체를 본다.
"""

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

EMPTY = {"nodes": [], "edges": []}


@pytest.fixture
def request_stub(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_factory=factory)))


async def _names(session) -> list[str]:
    rows = await session.execute(sqlalchemy.select(GuardrailModel.name))
    return sorted(rows.scalars().all())


async def test_the_success_path_commits(request_stub, session):
    agen = provide_guardrail_service(request_stub)
    service = await agen.__anext__()
    await service.create(CreateGuardrail(name="kept", graph=EMPTY))
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()

    assert await _names(session) == ["kept"]


async def test_an_exception_after_a_write_commits_nothing(request_stub, session):
    """FastAPI 는 라우트의 예외를 yield 지점으로 다시 던진다."""
    agen = provide_guardrail_service(request_stub)
    service = await agen.__anext__()
    await service.create(CreateGuardrail(name="ghost", graph=EMPTY))

    with pytest.raises(RuntimeError):
        await agen.athrow(RuntimeError("route blew up"))

    assert await _names(session) == []


async def test_each_request_gets_its_own_session(request_stub):
    """서비스 인스턴스가 다른 것은 당연하다 — 세션이 달라야 의미가 있다.

    세션이 공유되면 한 요청의 미커밋 쓰기가 다른 요청에 보이고, 한쪽의 롤백이
    다른 쪽을 되돌린다.
    """
    first = await (agen_a := provide_guardrail_service(request_stub)).__anext__()
    second = await (agen_b := provide_guardrail_service(request_stub)).__anext__()
    assert first._guardrails._session is not second._guardrails._session
    assert first._guardrails._session is first._dao._session, "한 요청 안에서는 같아야 한다"

    for agen in (agen_a, agen_b):
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()


async def test_an_uncommitted_request_is_invisible_to_another(request_stub, session):
    """세션이 공유되면 실패한 요청의 쓰기가 다른 요청에 보인다."""
    agen = provide_guardrail_service(request_stub)
    service = await agen.__anext__()
    await service.create(CreateGuardrail(name="pending", graph=EMPTY))

    other = await (other_agen := provide_guardrail_service(request_stub)).__anext__()
    page = await other.list()
    assert page.items == []

    with pytest.raises(StopAsyncIteration):
        await other_agen.__anext__()
    with pytest.raises(RuntimeError):
        await agen.athrow(RuntimeError("boom"))
    assert await _names(session) == []


# --- FastAPI 계약 ------------------------------------------------------------


@pytest_asyncio.fixture
async def app(engine, ch_client):
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def test_a_route_that_fails_after_writing_commits_nothing(app, session):
    """외부 계약을 우리 제너레이터가 아니라 앱을 통과해서 고정한다.

    FastAPI 가 yield 의존성의 되감기를 예외 핸들러보다 *먼저* 하지 않으면 커밋이
    돌아 절반 쓰인 상태가 남는다. 버전이 올라갈 때 조용히 깨질 수 있는 자리다.
    """

    @app.post("/write-then-boom")
    async def write_then_boom(service: GuardrailServiceDep):
        await service.create(CreateGuardrail(name="ghost-route", graph=EMPTY))
        raise RuntimeError("kaboom")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/write-then-boom")
    assert r.status_code == 500

    assert await _names(session) == []


async def test_a_route_that_succeeds_commits(app, session):
    """위 테스트가 '아무것도 커밋되지 않는다'로 통과하는 빈 단정이 아님을 보인다."""

    @app.post("/write-then-ok")
    async def write_then_ok(service: GuardrailServiceDep):
        await service.create(CreateGuardrail(name="kept-route", graph=EMPTY))
        return {"ok": True}

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/write-then-ok")
    assert r.status_code == 200

    assert await _names(session) == ["kept-route"]
