import pytest
import sqlalchemy

from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import DRAFT_VERSION, Edge, Guardrail, Node, NodeType
from gateway.infrastructure.models.guardrail import GuardrailModel
from gateway.infrastructure.repository.guardrail_repository import SqlAlchemyGuardrailRepository
from shared_kernel.exception import ConflictError, NotFoundError


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


async def test_add_then_find_draft(repo):
    await repo.add(_draft(), id="g1")
    found = await repo.find_draft("doc-agent")
    assert found == _draft()


async def test_find_draft_returns_none_when_absent(repo):
    assert await repo.find_draft("nope") is None


async def test_find_draft_ignores_published_rows(repo):
    """draft 조회가 발행본을 집으면 편집 대상이 뒤바뀐다."""
    await repo.add(_draft().published_as(1), id="g-v1")
    assert await repo.find_draft("doc-agent") is None


async def test_find_published_returns_the_latest_by_default(repo):
    await repo.add(_draft(max_chars=10).published_as(1), id="a")
    await repo.add(_draft(max_chars=20).published_as(2), id="b")

    latest = await repo.find_published("doc-agent")
    assert latest is not None
    assert latest.version_number == 2


async def test_find_published_orders_numerically_not_lexically(repo):
    """'10' < '9' 는 문자열 정렬이다. version_number 로 정렬해야 한다."""
    for n in (9, 10):
        await repo.add(_draft().published_as(n), id=f"g{n}")

    latest = await repo.find_published("doc-agent")
    assert latest is not None
    assert latest.version_number == 10


async def test_find_published_can_target_a_specific_version(repo):
    await repo.add(_draft(max_chars=10).published_as(1), id="a")
    await repo.add(_draft(max_chars=20).published_as(2), id="b")

    first = await repo.find_published("doc-agent", 1)
    assert first is not None
    assert first.nodes[1].config["max_chars"] == 10


async def test_find_published_returns_none_for_an_unknown_version(repo):
    await repo.add(_draft().published_as(1), id="a")
    assert await repo.find_published("doc-agent", 7) is None


async def test_find_published_returns_none_when_only_a_draft_exists(repo):
    await repo.add(_draft(), id="g1")
    assert await repo.find_published("doc-agent") is None


async def test_find_published_is_scoped_to_the_name(repo):
    await repo.add(_draft("other").published_as(1), id="a")
    assert await repo.find_published("doc-agent") is None


async def test_next_version_number_starts_at_one(repo):
    assert await repo.next_version_number("doc-agent") == 1


async def test_next_version_number_increments_past_the_highest(repo):
    await repo.add(_draft().published_as(1), id="a")
    await repo.add(_draft().published_as(2), id="b")
    assert await repo.next_version_number("doc-agent") == 3


async def test_next_version_number_ignores_other_names(repo):
    """번호는 가드레일마다 독립이다."""
    await repo.add(_draft("other").published_as(5), id="a")
    assert await repo.next_version_number("doc-agent") == 1


async def test_next_version_number_ignores_the_draft(repo):
    await repo.add(_draft(), id="g1")
    assert await repo.next_version_number("doc-agent") == 1


async def test_replace_draft_overwrites_in_place(repo, session):
    await repo.add(_draft(max_chars=10), id="g1")
    await repo.replace_draft(_draft(max_chars=999))
    await session.commit()

    rows = (
        (
            await session.execute(
                sqlalchemy.select(GuardrailModel).where(
                    GuardrailModel.version == DRAFT_VERSION,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].id == "g1", "draft 행이 새로 생기면 안 된다"
    assert rows[0].graph["nodes"][1]["config"]["max_chars"] == 999


async def test_replace_draft_does_not_touch_published_rows(repo):
    """발행본 불변성 — draft 를 고쳐도 발행된 그래프는 그대로다."""
    await repo.add(_draft(max_chars=10), id="g1")
    await repo.add(_draft(max_chars=10).published_as(1), id="g-v1")

    await repo.replace_draft(_draft(max_chars=999))

    published = await repo.find_published("doc-agent", 1)
    assert published is not None
    assert published.nodes[1].config["max_chars"] == 10


async def test_replace_draft_fails_without_a_draft(repo):
    with pytest.raises(NotFoundError) as exc:
        await repo.replace_draft(_draft())
    assert exc.value.code == GuardrailError.NO_DRAFT.code


async def test_exists_reports_any_row_for_the_name(repo):
    """이름 중복 검사는 draft 만 보면 안 된다 — 발행만 남은 이름도 점유 상태다."""
    assert await repo.exists("doc-agent") is False
    await repo.add(_draft().published_as(1), id="a")
    assert await repo.exists("doc-agent") is True


# --- 경합 번역 ---------------------------------------------------------------


async def test_a_duplicate_draft_becomes_a_domain_conflict(repo, session):
    """사전 확인과 유일 제약 사이의 틈. 지는 쪽이 500 이 아니라 409 를 받아야 한다."""
    await repo.add(_draft(), id="a")
    with pytest.raises(ConflictError) as exc:
        await repo.add(_draft(), id="b")
    assert exc.value.code == GuardrailError.NAME_TAKEN.code
    await session.rollback()


async def test_a_duplicate_published_version_becomes_a_domain_conflict(repo, session):
    """발행 버튼을 두 번 누르면 두 요청이 같은 번호를 계산한다."""
    await repo.add(_draft().published_as(1), id="a")
    with pytest.raises(ConflictError) as exc:
        await repo.add(_draft().published_as(1), id="b")
    assert exc.value.code == GuardrailError.CONCURRENT_WRITE.code
    await session.rollback()


async def test_the_conflict_keeps_the_original_cause(repo, session):
    """원인을 버리면 예상 못한 제약 위반이 NAME_TAKEN 으로 위장된다."""
    await repo.add(_draft(), id="a")
    with pytest.raises(ConflictError) as exc:
        await repo.add(_draft(), id="b")
    assert isinstance(exc.value.__cause__, sqlalchemy.exc.IntegrityError)
    await session.rollback()
