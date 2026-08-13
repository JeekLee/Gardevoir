import pytest
import sqlalchemy
import sqlalchemy.exc

from gateway.domain.models.api_key import ApiKey, generate_key, hash_key
from gateway.infrastructure.mappers.api_key import to_domain, to_model
from gateway.infrastructure.models.api_key import ApiKeyModel
from gateway.infrastructure.repository.api_key_repository import (
    SqlAlchemyApiKeyRepository,
)


def _key(raw: str, **kw) -> ApiKey:
    fields: dict = {
        "id": "k-repo",
        "name": "repo-test",
        "key_hash": hash_key(raw),
        "upstream_base_url": "https://api.openai.com/v1",
        "upstream_api_key": "sk-upstream",
        "allowed_guardrails": ("base", "doc-agent"),
        "default_guardrail": "base",
        "disabled": False,
    }
    fields.update(kw)
    return ApiKey(**fields)


def test_mapper_roundtrip_preserves_every_field():
    raw = generate_key()
    key = _key(raw)
    assert to_domain(to_model(key)) == key


def test_mapper_returns_guardrails_as_a_tuple():
    """jsonb는 list로 돌아온다. 도메인은 불변이어야 하므로 tuple로 바꿔야 한다."""
    model = ApiKeyModel(
        id="k1",
        name="n",
        key_hash="h",
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=["base"],
        default_guardrail="base",
        disabled=False,
    )
    assert to_domain(model).allowed_guardrails == ("base",)


def test_mapper_tolerates_null_guardrails():
    """jsonb 기본값이 비어 있어도 도메인이 만들어져야 한다."""
    model = ApiKeyModel(
        id="k1",
        name="n",
        key_hash="h",
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=None,
        default_guardrail=None,
        disabled=False,
    )
    assert to_domain(model).allowed_guardrails == ()


async def test_add_then_find_by_hash(session):
    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw))
    await session.commit()

    found = await repo.find_by_hash(hash_key(raw))
    assert found is not None
    assert found.id == "k-repo"
    assert found.upstream_api_key == "sk-upstream"
    assert found.allowed_guardrails == ("base", "doc-agent")


async def test_find_by_hash_returns_none_for_unknown(session):
    repo = SqlAlchemyApiKeyRepository(session)
    assert await repo.find_by_hash(hash_key(generate_key())) is None


async def test_disabled_key_is_not_returned(session):
    """비활성 키가 조회되면 키 회수가 무의미해진다."""
    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw, id="k-off", disabled=True))
    await session.commit()

    assert await repo.find_by_hash(hash_key(raw)) is None


async def test_duplicate_hash_is_rejected_by_the_database(session):
    """같은 키가 두 번 등록되면 어느 쪽이 유효한지 알 수 없다.

    add()가 flush 하므로 위반이 commit 이 아니라 add 에서 드러난다 — 호출자가
    실패를 더 이른 지점에서 보게 되는 것이 유리하다.
    """
    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw, id="k-a"))
    await session.commit()

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await repo.add(_key(raw, id="k-b", name="other"))
    await session.rollback()


async def test_raw_key_is_never_stored(session):
    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw))
    await session.commit()

    row = (await session.execute(sqlalchemy.select(ApiKeyModel))).scalar_one()
    for value in (row.key_hash, row.name, row.upstream_api_key, row.upstream_base_url):
        assert raw not in value


async def test_timestamps_are_populated_by_the_database(session):
    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw))
    await session.commit()

    row = (await session.execute(sqlalchemy.select(ApiKeyModel))).scalar_one()
    assert row.created_at is not None
    assert row.updated_at is not None
    assert row.created_at.tzinfo is not None


# --- 스코프 왕복 -------------------------------------------------------------


def test_mapper_round_trips_scopes():
    from gateway.domain.models.api_key import Scope

    raw = generate_key()
    key = _key(raw, scopes=(Scope.PROXY, Scope.ADMIN))
    assert to_domain(to_model(key)).scopes == (Scope.PROXY, Scope.ADMIN)


def test_mapper_stores_scopes_as_strings():
    """jsonb 에는 StrEnum 이 아니라 문자열이 들어가야 한다."""
    from gateway.domain.models.api_key import Scope

    model = to_model(_key(generate_key(), scopes=(Scope.ADMIN,)))
    assert model.scopes == ["admin"]
    assert all(isinstance(s, str) and type(s) is str for s in model.scopes)


def test_mapper_drops_unknown_scope_strings():
    """오타가 권한을 주면 안 된다. 알 수 없는 값은 버리고 proxy 로 떨어진다."""
    from gateway.domain.models.api_key import Scope

    model = ApiKeyModel(
        id="k1",
        name="n",
        key_hash="h",
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=["base"],
        default_guardrail="base",
        disabled=False,
        scopes=["admn", "superuser"],  # 오타 + 존재하지 않는 스코프
    )
    assert to_domain(model).scopes == (Scope.PROXY,)


def test_mapper_defaults_to_proxy_when_scopes_are_empty():
    from gateway.domain.models.api_key import Scope

    model = ApiKeyModel(
        id="k1",
        name="n",
        key_hash="h",
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=["base"],
        default_guardrail="base",
        disabled=False,
        scopes=[],
    )
    assert to_domain(model).scopes == (Scope.PROXY,)


async def test_scopes_survive_the_database(session):
    """DB 를 거쳐도 스코프가 유지되어야 한다 — 여기가 실제 경로다."""
    from gateway.domain.models.api_key import Scope

    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw, id="k-admin", scopes=(Scope.PROXY, Scope.ADMIN)))
    await session.commit()

    found = await repo.find_by_hash(hash_key(raw))
    assert found is not None
    assert found.scopes == (Scope.PROXY, Scope.ADMIN)
    assert found.has_scope(Scope.ADMIN)


async def test_default_key_persists_as_proxy_only(session):
    from gateway.domain.models.api_key import Scope

    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw, id="k-default"))
    await session.commit()

    found = await repo.find_by_hash(hash_key(raw))
    assert found is not None
    assert found.scopes == (Scope.PROXY,)
    assert found.has_scope(Scope.ADMIN) is False
