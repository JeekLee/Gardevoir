from sqlalchemy import select

from gateway.application.service.authentication_service import AuthenticationService
from gateway.cli import create_key
from gateway.domain.models.api_key import KEY_PREFIX, hash_key
from gateway.infrastructure.models.api_key import ApiKeyModel
from gateway.infrastructure.repository import SqlAlchemyApiKeyRepository


async def test_create_key_persists_only_the_hash(session):
    raw = await create_key(
        session=session,
        name="e2e",
        upstream_base_url="https://api.openai.com/v1",
        upstream_api_key="sk-upstream",
        allowed_guardrails=["base"],
        default_guardrail="base",
    )
    await session.commit()

    assert raw.startswith(KEY_PREFIX)
    row = (await session.execute(select(ApiKeyModel))).scalar_one()
    assert row.key_hash == hash_key(raw)
    assert raw not in row.key_hash
    assert row.allowed_guardrails == ["base"]
    assert row.default_guardrail == "base"
    assert row.disabled is False


async def test_each_call_produces_a_distinct_key(session):
    raws = [
        await create_key(
            session=session,
            name=f"k{i}",
            upstream_base_url="u",
            upstream_api_key="s",
            allowed_guardrails=["base"],
            default_guardrail="base",
        )
        for i in range(3)
    ]
    await session.commit()
    assert len(set(raws)) == 3

    rows = (await session.execute(select(ApiKeyModel))).scalars().all()
    assert len({r.id for r in rows}) == 3


async def test_created_key_authenticates(session):
    raw = await create_key(
        session=session,
        name="e2e2",
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=["base", "doc-agent"],
        default_guardrail="base",
    )
    await session.commit()

    service = AuthenticationService(keys=SqlAlchemyApiKeyRepository(session))
    result = await service.authenticate(
        authorization=f"Bearer {raw}", guardrail="doc-agent", mode=None
    )
    assert result.guardrail == "doc-agent"
    assert result.key.upstream_api_key == "s"


async def test_id_is_a_ulid(session):
    """ULID 는 시간순 정렬을 주므로 나중에 발급 순서를 알 수 있다."""
    raw = await create_key(
        session=session,
        name="ulid",
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=["base"],
        default_guardrail="base",
    )
    await session.commit()
    assert raw

    row = (await session.execute(select(ApiKeyModel))).scalar_one()
    assert len(row.id) == 26
