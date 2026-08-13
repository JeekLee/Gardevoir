import pytest
import sqlalchemy

from gateway.application.command.guardrail_command import CreateGuardrail, UpdateDraft
from gateway.application.result.guardrail_result import GuardrailDetail
from gateway.application.service.guardrail_service import GuardrailService
from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import DRAFT_VERSION
from gateway.infrastructure.dao.guardrail_dao import SqlAlchemyGuardrailDao
from gateway.infrastructure.models.guardrail import GuardrailModel
from gateway.infrastructure.repository.guardrail_repository import SqlAlchemyGuardrailRepository
from shared_kernel.api import Page
from shared_kernel.exception import (
    ConflictError,
    NotFoundError,
    ValidationError,
)


def _graph(max_chars: int = 100) -> dict:
    return {
        "nodes": [
            {"id": "n0", "type": "extract", "config": {"checkpoint": "input"}},
            {"id": "n1", "type": "length", "config": {"max_chars": max_chars}},
            {
                "id": "n2",
                "type": "verdict",
                "config": {"decision": "conclusive", "action": "block"},
            },
        ],
        "edges": [{"src": "n0", "dst": "n1"}, {"src": "n1", "dst": "n2"}],
    }


CYCLIC = {
    "nodes": [
        {"id": "a", "type": "transform", "config": {"op": "lower"}},
        {"id": "b", "type": "transform", "config": {"op": "strip"}},
    ],
    "edges": [{"src": "a", "dst": "b"}, {"src": "b", "dst": "a"}],
}

BAD_CONFIG = {"nodes": [{"id": "n9", "type": "length", "config": {"max_chars": -1}}], "edges": []}


@pytest.fixture
def service(session):
    return GuardrailService(
        guardrails=SqlAlchemyGuardrailRepository(session),
        dao=SqlAlchemyGuardrailDao(session),
    )


# -- create ------------------------------------------------------------------


async def test_create_makes_a_draft(service):
    detail = await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    assert isinstance(detail, GuardrailDetail)
    assert detail.version == DRAFT_VERSION
    assert detail.version_number is None
    assert [n["id"] for n in detail.graph["nodes"]] == ["n0", "n1", "n2"]


async def test_create_rejects_a_duplicate_name(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    with pytest.raises(ConflictError) as exc:
        await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    assert exc.value.code == GuardrailError.NAME_TAKEN.code


async def test_create_rejects_a_name_already_taken_by_a_published_row(service, session):
    """발행만 남은 이름도 점유 상태다 — draft 만 보면 이름이 겹친다."""
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    await service.publish("doc-agent")
    await session.execute(
        sqlalchemy.delete(GuardrailModel).where(GuardrailModel.version == DRAFT_VERSION)
    )

    with pytest.raises(ConflictError):
        await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))


async def test_create_validates_the_graph(service):
    with pytest.raises(ValidationError) as exc:
        await service.create(CreateGuardrail(name="looping", graph=CYCLIC))
    assert exc.value.code == GuardrailError.CYCLE.code


async def test_create_rejects_an_invalid_name(service):
    with pytest.raises(ValidationError) as exc:
        await service.create(CreateGuardrail(name="Doc Agent!", graph=_graph()))
    assert exc.value.code == GuardrailError.INVALID_NAME.code


async def test_a_rejected_create_stores_nothing(service, session):
    with pytest.raises(ValidationError):
        await service.create(CreateGuardrail(name="looping", graph=CYCLIC))

    rows = (await session.execute(sqlalchemy.select(GuardrailModel))).scalars().all()
    assert rows == []


# -- update_draft ------------------------------------------------------------


async def test_update_draft_replaces_the_graph(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph(10)))
    detail = await service.update_draft("doc-agent", UpdateDraft(graph=_graph(999)))
    assert detail.graph["nodes"][1]["config"]["max_chars"] == 999


async def test_update_draft_validates(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    with pytest.raises(ValidationError) as exc:
        await service.update_draft("doc-agent", UpdateDraft(graph=BAD_CONFIG))
    assert exc.value.code == GuardrailError.INVALID_NODE_CONFIG.code
    assert exc.value.details is not None
    assert exc.value.details["node_id"] == "n9"


async def test_update_draft_fails_without_a_draft(service):
    with pytest.raises(NotFoundError) as exc:
        await service.update_draft("doc-agent", UpdateDraft(graph=_graph()))
    assert exc.value.code == GuardrailError.NO_DRAFT.code


async def test_a_rejected_update_leaves_the_draft_alone(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph(10)))
    with pytest.raises(ValidationError):
        await service.update_draft("doc-agent", UpdateDraft(graph=CYCLIC))

    draft = await service.get_draft("doc-agent")
    assert draft.graph["nodes"][1]["config"]["max_chars"] == 10


# -- publish -----------------------------------------------------------------


async def test_publish_assigns_version_one_first(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    detail = await service.publish("doc-agent")
    assert detail.version == "1"
    assert detail.version_number == 1


async def test_publish_increments(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    await service.publish("doc-agent")
    second = await service.publish("doc-agent")
    assert second.version_number == 2


async def test_publish_fails_without_a_draft(service):
    with pytest.raises(NotFoundError) as exc:
        await service.publish("doc-agent")
    assert exc.value.code == GuardrailError.NO_DRAFT.code


async def test_a_failed_publish_writes_no_row(service, session):
    """검증이 쓰기보다 앞서야 한다.

    번호 자체는 max()+1 로 유도되므로 next_version_number 를 부르는 것만으로는
    소모되지 않는다 — 소모되는 것은 *행이 남을* 때다. 그러면 버전 열에 구멍이
    생기고 감사 추적에서 "2번은 어디 갔나"를 설명할 수 없게 된다.
    """
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    await service.publish("doc-agent")

    # draft 를 직접 망가뜨린다 — update_draft 는 검증 때문에 통과하지 못한다.
    await session.execute(
        sqlalchemy.update(GuardrailModel)
        .where(GuardrailModel.version == DRAFT_VERSION)
        .values(graph=BAD_CONFIG)
    )

    with pytest.raises(ValidationError):
        await service.publish("doc-agent")

    versions = (
        (
            await session.execute(
                sqlalchemy.select(GuardrailModel.version).where(
                    GuardrailModel.version_number.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(versions) == ["1"], "실패한 발행이 행을 남겼다"

    await service.update_draft("doc-agent", UpdateDraft(graph=_graph()))
    revived = await service.publish("doc-agent")
    assert revived.version_number == 2


async def test_publish_leaves_the_draft_editable(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph(10)))
    await service.publish("doc-agent")

    draft = await service.get_draft("doc-agent")
    assert draft.version == DRAFT_VERSION

    updated = await service.update_draft("doc-agent", UpdateDraft(graph=_graph(999)))
    assert updated.graph["nodes"][1]["config"]["max_chars"] == 999


async def test_published_rows_are_never_rewritten(service):
    """발행 후 draft 를 고쳐도 발행본은 그대로다."""
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph(10)))
    await service.publish("doc-agent")
    await service.update_draft("doc-agent", UpdateDraft(graph=_graph(999)))

    published = await service.get_version("doc-agent", 1)
    assert published.graph["nodes"][1]["config"]["max_chars"] == 10


async def test_publish_captures_the_draft_at_that_moment(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph(10)))
    await service.publish("doc-agent")
    await service.update_draft("doc-agent", UpdateDraft(graph=_graph(20)))
    await service.publish("doc-agent")

    first = await service.get_version("doc-agent", 1)
    second = await service.get_version("doc-agent", 2)
    assert first.graph["nodes"][1]["config"]["max_chars"] == 10
    assert second.graph["nodes"][1]["config"]["max_chars"] == 20


# -- reads -------------------------------------------------------------------


async def test_get_latest_returns_the_newest_published(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph(10)))
    await service.publish("doc-agent")
    await service.update_draft("doc-agent", UpdateDraft(graph=_graph(20)))
    await service.publish("doc-agent")

    latest = await service.get_latest("doc-agent")
    assert latest.version_number == 2


async def test_get_latest_is_404_when_only_a_draft_exists(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    with pytest.raises(NotFoundError) as exc:
        await service.get_latest("doc-agent")
    assert exc.value.code == GuardrailError.NOT_FOUND.code


async def test_get_latest_is_404_for_an_unknown_name(service):
    with pytest.raises(NotFoundError):
        await service.get_latest("nope")


async def test_get_draft_is_404_for_an_unknown_name(service):
    with pytest.raises(NotFoundError) as exc:
        await service.get_draft("nope")
    assert exc.value.code == GuardrailError.NO_DRAFT.code


async def test_get_version_is_404_for_an_unknown_version(service):
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    with pytest.raises(NotFoundError) as exc:
        await service.get_version("doc-agent", 7)
    assert exc.value.code == GuardrailError.NOT_FOUND.code


async def test_list_returns_a_page(service):
    await service.create(CreateGuardrail(name="alpha", graph=_graph()))
    await service.create(CreateGuardrail(name="bravo", graph=_graph()))
    await service.publish("bravo")

    page = await service.list()
    assert isinstance(page, Page)
    assert page.total == 2
    assert [s.name for s in page.items] == ["alpha", "bravo"]
    assert page.items[0].latest_version_number is None
    assert page.items[1].latest_version_number == 1


async def test_list_is_empty_without_guardrails(service):
    page = await service.list()
    assert page.items == []
    assert page.total == 0


async def test_every_write_returns_the_same_shape_as_a_read(service):
    """§5: 경계에 DTO 하나. 생성·발행·조회가 같은 형태여야 한다."""
    created = await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    published = await service.publish("doc-agent")
    read = await service.get_latest("doc-agent")

    assert type(created) is type(published) is type(read) is GuardrailDetail
    assert published.model_dump() == read.model_dump()


# -- 이름 -------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["x\x00y", "A", "a" * 65, "", "a/b"])
async def test_every_read_rejects_an_invalid_name(service, bad):
    """이름 규칙이 쓰기 경로에만 걸려 있으면 조회가 그 문자열을 그대로 DB 로 보낸다."""
    for call in (
        service.get_draft(bad),
        service.get_latest(bad),
        service.get_version(bad, 1),
        service.publish(bad),
    ):
        with pytest.raises(ValidationError) as exc:
            await call
        assert exc.value.code == GuardrailError.INVALID_NAME.code


async def test_update_draft_rejects_an_invalid_name(service):
    with pytest.raises(ValidationError) as exc:
        await service.update_draft("x\x00y", UpdateDraft(graph=_graph()))
    assert exc.value.code == GuardrailError.INVALID_NAME.code


# -- arity -------------------------------------------------------------------

ORPHAN_REGEX = {"nodes": [{"id": "r", "type": "regex", "config": {"pattern": "x"}}], "edges": []}


async def test_create_rejects_a_node_with_no_input(service):
    """컴파일러는 regex 가 읽을 슬롯이 하나라고 가정한다 (§6, Phase 2b)."""
    with pytest.raises(ValidationError) as exc:
        await service.create(CreateGuardrail(name="orphan", graph=ORPHAN_REGEX))
    assert exc.value.code == GuardrailError.INVALID_ARITY.code
    assert exc.value.details["node_id"] == "r"


async def test_publish_rejects_a_node_with_no_input(service, session):
    """저작 시점에 통과했더라도 발행이 다시 본다 — 규칙이 나중에 추가될 수 있다."""
    await service.create(CreateGuardrail(name="doc-agent", graph=_graph()))
    await session.execute(
        sqlalchemy.update(GuardrailModel)
        .where(GuardrailModel.version == DRAFT_VERSION)
        .values(graph=ORPHAN_REGEX)
    )

    with pytest.raises(ValidationError) as exc:
        await service.publish("doc-agent")
    assert exc.value.code == GuardrailError.INVALID_ARITY.code
