"""GuardrailSource 의 DB 어댑터.

레지스트리는 프로세스 수명, 세션은 요청 수명이다. 어댑터가 호출마다 짧은 세션을 연다.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from gateway.domain.models.guardrail import DRAFT_VERSION, Edge, Guardrail, Node, NodeType
from gateway.infrastructure.plan.guardrail_source import SessionScopedGuardrailSource
from gateway.infrastructure.repository.guardrail_repository import SqlAlchemyGuardrailRepository


def _guardrail(name: str, *, pattern: str = "alpha") -> Guardrail:
    return Guardrail(
        name=name,
        version=DRAFT_VERSION,
        version_number=None,
        nodes=(
            Node(id="e", type=NodeType.EXTRACT, config={"checkpoint": "input"}),
            Node(id="r", type=NodeType.REGEX, config={"pattern": pattern}),
        ),
        edges=(Edge("e", "r"),),
    )


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def source(factory):
    return SessionScopedGuardrailSource(factory)


async def _publish(factory, guardrail: Guardrail, version_number: int, row_id: str) -> None:
    async with factory() as session:
        await SqlAlchemyGuardrailRepository(session).add(
            guardrail.published_as(version_number), id=row_id
        )
        await session.commit()


async def test_latest_versions_is_empty_without_rows(source, session):
    assert await source.latest_versions() == {}


async def test_latest_versions_reports_the_highest(source, factory, session):
    await _publish(factory, _guardrail("a"), 1, "a1")
    await _publish(factory, _guardrail("a"), 2, "a2")
    await _publish(factory, _guardrail("b"), 1, "b1")

    assert await source.latest_versions() == {"a": 2, "b": 1}


async def test_latest_versions_orders_numerically(source, factory, session):
    """'10' < '9' 는 문자열 정렬이다."""
    await _publish(factory, _guardrail("a"), 9, "a9")
    await _publish(factory, _guardrail("a"), 10, "a10")

    assert await source.latest_versions() == {"a": 10}


async def test_latest_versions_excludes_drafts(source, factory, session):
    """draft 는 운영에 영향이 없다 (§6)."""
    async with factory() as inner:
        await SqlAlchemyGuardrailRepository(inner).add(_guardrail("only-draft"), id="d1")
        await inner.commit()

    assert await source.latest_versions() == {}


async def test_load_published_returns_the_graph(source, factory, session):
    await _publish(factory, _guardrail("a", pattern="bravo"), 1, "a1")

    loaded = await source.load_published("a", 1)
    assert loaded is not None
    assert loaded.version_number == 1
    assert loaded.nodes[1].config["pattern"] == "bravo"


async def test_load_published_distinguishes_versions(source, factory, session):
    await _publish(factory, _guardrail("a", pattern="one"), 1, "a1")
    await _publish(factory, _guardrail("a", pattern="two"), 2, "a2")

    first = await source.load_published("a", 1)
    second = await source.load_published("a", 2)
    assert first is not None and second is not None
    assert first.nodes[1].config["pattern"] == "one"
    assert second.nodes[1].config["pattern"] == "two"


async def test_load_published_returns_none_when_absent(source, session):
    assert await source.load_published("nope", 1) is None


async def test_load_published_is_scoped_to_the_name(source, factory, session):
    await _publish(factory, _guardrail("other"), 1, "o1")
    assert await source.load_published("a", 1) is None


async def test_load_published_ignores_the_draft(source, factory, session):
    async with factory() as inner:
        await SqlAlchemyGuardrailRepository(inner).add(_guardrail("a"), id="d1")
        await inner.commit()

    assert await source.load_published("a", 1) is None


async def test_each_call_opens_its_own_session(factory, session):
    opened = []

    def counting():
        inner = factory()
        opened.append(inner)
        return inner

    source = SessionScopedGuardrailSource(counting)
    await source.latest_versions()
    await source.load_published("nope", 1)

    assert len(opened) == 2, "호출마다 세션을 열어야 한다"


async def test_calls_return_their_connections_to_the_pool(source, engine, session):
    """커넥션을 들고 있으면 폴링 주기마다 하나씩 잠겨서 결국 풀이 마른다."""
    pool = engine.sync_engine.pool
    baseline = pool.checkedout()

    for _ in range(20):
        await source.latest_versions()
        await source.load_published("nope", 1)

    assert pool.checkedout() == baseline
