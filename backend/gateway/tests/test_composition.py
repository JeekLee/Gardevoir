"""트랜잭션 경계.

라우트가 예외를 올렸을 때 절반 쓰인 상태가 커밋되지 않아야 한다. 서비스 테스트로는
드러나지 않는다 — 대부분의 실패는 검증 단계에서 나서 아직 쓴 것이 없기 때문이다.
여기서는 쓰기가 성공한 뒤에 실패를 주입해 경계 자체를 본다.
"""

from types import SimpleNamespace

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import async_sessionmaker

from gateway.application.command.guardrail_command import CreateGuardrail
from gateway.composition import provide_guardrail_service
from gateway.infrastructure.models.guardrail import GuardrailModel

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
    first = await (agen_a := provide_guardrail_service(request_stub)).__anext__()
    second = await (agen_b := provide_guardrail_service(request_stub)).__anext__()
    assert first is not second

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
