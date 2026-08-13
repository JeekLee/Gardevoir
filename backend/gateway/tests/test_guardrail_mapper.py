import pytest
import sqlalchemy
import sqlalchemy.exc

from gateway.domain.models.guardrail import (
    DRAFT_VERSION,
    Decision,
    Edge,
    Guardrail,
    Node,
    NodeType,
    VerdictAction,
)
from gateway.infrastructure.mappers.guardrail import to_domain, to_model
from gateway.infrastructure.models.guardrail import GuardrailModel


def _graph() -> Guardrail:
    return Guardrail(
        name="doc-agent",
        version=DRAFT_VERSION,
        version_number=None,
        nodes=(
            Node(id="n0", type=NodeType.EXTRACT, config={"checkpoint": "output"}),
            Node(id="n1", type=NodeType.REGEX, config={"pattern": r"\d{6}-\d{7}"}),
            Node(
                id="n2",
                type=NodeType.VERDICT,
                config={"decision": Decision.CONCLUSIVE, "action": VerdictAction.BLOCK},
            ),
        ),
        edges=(Edge("n0", "n1"), Edge("n1", "n2")),
    )


def test_mapper_roundtrip_preserves_the_graph():
    original = _graph()
    assert to_domain(to_model(original, id="g1")) == original


def test_mapper_returns_tuples():
    """jsonb 는 list 로 돌아온다. 도메인은 불변이어야 한다."""
    restored = to_domain(to_model(_graph(), id="g1"))
    assert isinstance(restored.nodes, tuple)
    assert isinstance(restored.edges, tuple)


def test_mapper_tolerates_an_empty_graph():
    empty = Guardrail(name="empty", version=DRAFT_VERSION, version_number=None, nodes=(), edges=())
    model = to_model(empty, id="g-empty")
    assert model.graph == {"nodes": [], "edges": []}
    assert to_domain(model) == empty


def test_mapper_tolerates_a_missing_graph_key():
    """저장된 그래프에 키가 빠져 있어도 도메인이 만들어져야 한다."""
    model = GuardrailModel(id="g1", name="n", version=DRAFT_VERSION, version_number=None, graph={})
    restored = to_domain(model)
    assert restored.nodes == ()
    assert restored.edges == ()


def test_node_type_is_stored_as_a_plain_string():
    """jsonb 에 StrEnum 이 아니라 문자열이 들어가야 한다."""
    model = to_model(_graph(), id="g1")
    for node in model.graph["nodes"]:
        assert type(node["type"]) is str


def test_verdict_config_is_stored_as_plain_strings():
    model = to_model(_graph(), id="g1")
    verdict = next(n for n in model.graph["nodes"] if n["type"] == "verdict")
    assert type(verdict["config"]["decision"]) is str
    assert type(verdict["config"]["action"]) is str


def test_published_version_round_trips():
    published = _graph().published_as(3)
    model = to_model(published, id="g3")
    assert model.version == "3"
    assert model.version_number == 3
    assert to_domain(model) == published


# --- DB 제약 -----------------------------------------------------------------


async def test_draft_and_published_coexist_for_one_name(session):
    session.add(to_model(_graph(), id="g-draft"))
    session.add(to_model(_graph().published_as(1), id="g-v1"))
    await session.commit()

    rows = (await session.execute(sqlalchemy.select(GuardrailModel))).scalars().all()
    assert {r.version for r in rows} == {DRAFT_VERSION, "1"}


async def test_duplicate_name_and_version_is_rejected(session):
    """같은 이름에 같은 버전이 두 개면 어느 쪽이 유효한지 알 수 없다."""
    session.add(to_model(_graph(), id="a"))
    await session.commit()

    session.add(to_model(_graph(), id="b"))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await session.commit()
    await session.rollback()


async def test_duplicate_version_number_is_rejected(session):
    session.add(to_model(_graph().published_as(1), id="a"))
    await session.commit()

    session.add(
        GuardrailModel(id="b", name="doc-agent", version="1-dup", version_number=1, graph={})
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await session.commit()
    await session.rollback()


async def test_every_name_can_hold_a_draft(session):
    """이름 단독으로 유일해서는 안 된다. draft 는 가드레일마다 하나씩 있다."""
    for name in ("a", "b", "c"):
        session.add(
            GuardrailModel(
                id=f"g-{name}", name=name, version=DRAFT_VERSION, version_number=None, graph={}
            )
        )
    await session.commit()

    count = (await session.execute(sqlalchemy.select(GuardrailModel))).scalars().all()
    assert len(count) == 3


async def test_graph_is_queryable_as_jsonb(session):
    """§6: '이 regex 를 쓰는 가드레일이 어디 있나' 같은 질의가 가능해야 한다."""
    session.add(to_model(_graph(), id="g1"))
    await session.commit()

    found = (
        (
            await session.execute(
                sqlalchemy.text(
                    "SELECT name FROM guardrails, jsonb_array_elements(graph->'nodes') AS node "
                    "WHERE node->>'type' = 'regex' AND node->'config'->>'pattern' = :p"
                ),
                {"p": r"\d{6}-\d{7}"},
            )
        )
        .scalars()
        .all()
    )
    assert found == ["doc-agent"]
