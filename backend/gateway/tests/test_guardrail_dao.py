import pytest

from gateway.application.result.guardrail_result import GuardrailDetail, GuardrailSummary
from gateway.domain.models.guardrail import DRAFT_VERSION, Edge, Guardrail, Node, NodeType
from gateway.infrastructure.dao.guardrail_dao import SqlAlchemyGuardrailDao
from gateway.infrastructure.repository.guardrail_repository import SqlAlchemyGuardrailRepository


def _draft(name: str = "doc-agent", *, max_chars: int = 100) -> Guardrail:
    return Guardrail(
        name=name,
        version=DRAFT_VERSION,
        version_number=None,
        nodes=(
            Node(id="n0", type=NodeType.EXTRACT, config={"checkpoint": "input"}),
            Node(id="n1", type=NodeType.LENGTH, config={"max_chars": max_chars}),
        ),
        edges=(Edge("n0", "n1"),),
    )


@pytest.fixture
def repo(session):
    return SqlAlchemyGuardrailRepository(session)


@pytest.fixture
def dao(session):
    return SqlAlchemyGuardrailDao(session)


async def test_get_detail_returns_the_graph(repo, dao):
    await repo.add(_draft(), id="g1")
    detail = await dao.get_detail("doc-agent", DRAFT_VERSION)

    assert detail is not None
    assert detail.name == "doc-agent"
    assert detail.version == DRAFT_VERSION
    assert detail.version_number is None
    assert [n["id"] for n in detail.graph["nodes"]] == ["n0", "n1"]


async def test_get_detail_returns_a_result_dto(repo, dao):
    """DAO 는 도메인 애그리거트를 반환하지 않는다 (§5)."""
    await repo.add(_draft(), id="g1")
    detail = await dao.get_detail("doc-agent", DRAFT_VERSION)
    assert isinstance(detail, GuardrailDetail)
    assert not isinstance(detail, Guardrail)


async def test_get_detail_returns_none_when_absent(dao):
    assert await dao.get_detail("nope", DRAFT_VERSION) is None


async def test_get_detail_distinguishes_versions(repo, dao):
    await repo.add(_draft(max_chars=10), id="g1")
    await repo.add(_draft(max_chars=20).published_as(1), id="g-v1")

    draft = await dao.get_detail("doc-agent", DRAFT_VERSION)
    published = await dao.get_detail("doc-agent", "1")
    assert draft is not None and published is not None
    assert draft.graph["nodes"][1]["config"]["max_chars"] == 10
    assert published.graph["nodes"][1]["config"]["max_chars"] == 20


async def test_get_detail_carries_timestamps(repo, dao):
    await repo.add(_draft(), id="g1")
    detail = await dao.get_detail("doc-agent", DRAFT_VERSION)
    assert detail is not None
    assert detail.created_at is not None
    assert detail.updated_at is not None


async def test_get_latest_detail_returns_the_newest_published(repo, dao):
    for n, chars in ((1, 10), (2, 20)):
        await repo.add(_draft(max_chars=chars).published_as(n), id=f"v{n}")

    latest = await dao.get_latest_detail("doc-agent")
    assert latest is not None
    assert latest.version_number == 2
    assert latest.graph["nodes"][1]["config"]["max_chars"] == 20


async def test_get_latest_detail_orders_numerically(repo, dao):
    """'10' < '9' 는 문자열 정렬이다."""
    for n in (9, 10):
        await repo.add(_draft().published_as(n), id=f"v{n}")

    latest = await dao.get_latest_detail("doc-agent")
    assert latest is not None
    assert latest.version_number == 10


async def test_get_latest_detail_ignores_the_draft(repo, dao):
    await repo.add(_draft(), id="g1")
    assert await dao.get_latest_detail("doc-agent") is None


async def test_get_latest_detail_is_scoped_to_the_name(repo, dao):
    await repo.add(_draft("other").published_as(1), id="a")
    assert await dao.get_latest_detail("doc-agent") is None


async def test_list_summaries_reports_latest_and_draft_presence(repo, dao):
    await repo.add(_draft("with-both"), id="a")
    await repo.add(_draft("with-both").published_as(3), id="b")
    await repo.add(_draft("draft-only"), id="c")
    await repo.add(_draft("published-only").published_as(1), id="d")

    items, _ = await dao.list_summaries()
    by_name = {s.name: s for s in items}

    assert by_name["with-both"].latest_version_number == 3
    assert by_name["with-both"].has_draft is True
    assert by_name["draft-only"].latest_version_number is None
    assert by_name["draft-only"].has_draft is True
    assert by_name["published-only"].latest_version_number == 1
    assert by_name["published-only"].has_draft is False


async def test_list_summaries_reports_the_highest_version_number(repo, dao):
    """가장 최근 발행본이어야 한다 — 첫 발행본이 아니라."""
    for n in (1, 2, 3):
        await repo.add(_draft().published_as(n), id=f"v{n}")

    items, _ = await dao.list_summaries()
    assert items[0].latest_version_number == 3


async def test_list_summaries_returns_one_row_per_name(repo, dao):
    """행이 아니라 가드레일을 센다."""
    await repo.add(_draft(), id="a")
    for n in (1, 2, 3):
        await repo.add(_draft().published_as(n), id=f"v{n}")

    items, total = await dao.list_summaries()
    assert len(items) == 1
    assert total == 1


async def test_list_summaries_returns_total(repo, dao):
    for name in ("a", "b", "c"):
        await repo.add(_draft(name), id=name)
    items, total = await dao.list_summaries()
    assert total == 3
    assert len(items) == 3


async def test_list_summaries_is_empty_without_rows(dao):
    items, total = await dao.list_summaries()
    assert items == []
    assert total == 0


async def test_list_summaries_returns_result_dtos(repo, dao):
    await repo.add(_draft(), id="a")
    items, _ = await dao.list_summaries()
    assert all(isinstance(s, GuardrailSummary) for s in items)


async def test_list_summaries_is_ordered_by_name(repo, dao):
    """순서가 정해져 있지 않으면 목록 화면이 요청마다 흔들린다."""
    for name in ("charlie", "alpha", "bravo"):
        await repo.add(_draft(name), id=name)

    items, _ = await dao.list_summaries()
    assert [s.name for s in items] == ["alpha", "bravo", "charlie"]


async def test_list_summaries_reports_the_newest_update(repo, dao, session):
    """updated_at 은 그 이름의 어떤 행이든 가장 최근 것이어야 한다."""
    import sqlalchemy

    from gateway.infrastructure.models.guardrail import GuardrailModel

    await repo.add(_draft(), id="a")
    await repo.add(_draft().published_as(1), id="b")
    await session.commit()
    await session.execute(
        sqlalchemy.update(GuardrailModel)
        .where(GuardrailModel.id == "b")
        .values(updated_at=sqlalchemy.text("now() + interval '1 hour'"))
    )

    items, _ = await dao.list_summaries()
    newest = (
        await session.execute(
            sqlalchemy.select(GuardrailModel.updated_at).where(GuardrailModel.id == "b")
        )
    ).scalar_one()
    assert items[0].updated_at == newest
