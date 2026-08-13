import sys

import pytest
from sqlalchemy import select

from gateway import cli
from gateway.application.service.authentication_service import AuthenticationService
from gateway.cli import create_key
from gateway.domain.models.api_key import KEY_PREFIX, Scope, hash_key
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
        authorization=f"Bearer {raw}",
        guardrail="doc-agent",
        mode=None,
        require=Scope.PROXY,
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


# --- 인자 검증 ---------------------------------------------------------------


def _argv(*extra: str) -> list[str]:
    return ["gardevoir-createkey", "--name", "k", *extra]


def test_an_admin_only_key_does_not_need_an_upstream_secret(monkeypatch):
    """admin 전용 키는 그 시크릿을 쓸 수 없다.

    그래도 요구하면 컨트롤 플레인 크레덴셜 유출 시 프로바이더 키까지 함께 새고,
    운영자는 쓰지도 못하는 값을 붙여넣게 된다.
    """
    seen: dict = {}
    monkeypatch.setattr(sys, "argv", _argv("--scope", "admin"))
    # DB 를 건드리지 않는다 — 검사하려는 것은 인자 처리다.
    monkeypatch.setattr(cli, "_run", lambda args, guardrails: seen.update(args=args) or "x")
    monkeypatch.setattr(cli.asyncio, "run", lambda value: value)

    cli.createkey()
    assert seen["args"].upstream_api_key == ""
    assert seen["args"].scope == ["admin"]


def test_a_proxy_key_still_requires_an_upstream_secret(monkeypatch):
    monkeypatch.setattr(sys, "argv", _argv("--scope", "proxy"))
    with pytest.raises(SystemExit):
        cli.createkey()


def test_the_default_scope_requires_an_upstream_secret(monkeypatch):
    """스코프를 생략하면 proxy 다 — 그 경로가 검사에서 빠지면 안 된다."""
    monkeypatch.setattr(sys, "argv", _argv())
    with pytest.raises(SystemExit):
        cli.createkey()


def test_an_admin_and_proxy_key_requires_an_upstream_secret(monkeypatch):
    monkeypatch.setattr(sys, "argv", _argv("--scope", "admin", "--scope", "proxy"))
    with pytest.raises(SystemExit):
        cli.createkey()


async def test_an_admin_only_key_stores_no_upstream_secret(session):
    raw = await create_key(
        session=session,
        name="ops",
        upstream_base_url="https://api.openai.com/v1",
        upstream_api_key="",
        allowed_guardrails=[],
        default_guardrail=None,
        scopes=[str(Scope.ADMIN)],
    )
    await session.commit()
    assert raw

    row = (await session.execute(select(ApiKeyModel))).scalar_one()
    assert row.upstream_api_key == ""
    assert row.scopes == ["admin"]
