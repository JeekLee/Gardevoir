"""Operator entry points."""

import argparse
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from gateway.domain.models.api_key import ApiKey, Scope, generate_key, hash_key
from gateway.infrastructure.engine import dispose_engine, get_session_factory
from gateway.infrastructure.repository import SqlAlchemyApiKeyRepository
from gateway.settings import get_settings


async def create_key(
    *,
    session: AsyncSession,
    name: str,
    upstream_base_url: str,
    upstream_api_key: str,
    allowed_guardrails: list[str],
    default_guardrail: str | None,
    scopes: list[str] | None = None,
) -> str:
    """Create a key and return the raw value.

    Only the hash is stored, so this return value is the only time the key is
    visible. The caller commits.
    """
    raw = generate_key()
    key = ApiKey(
        id=str(ULID()),
        name=name,
        key_hash=hash_key(raw),
        upstream_base_url=upstream_base_url,
        upstream_api_key=upstream_api_key,
        allowed_guardrails=tuple(allowed_guardrails),
        default_guardrail=default_guardrail,
        scopes=tuple(Scope(s) for s in (scopes or [Scope.PROXY])),
    )
    await SqlAlchemyApiKeyRepository(session).add(key)
    return raw


def migrate() -> None:
    """Apply the ClickHouse audit schema. Postgres is handled by Alembic."""
    import pathlib

    import clickhouse_connect

    from gateway.infrastructure.audit.schema import apply_clickhouse_schema

    ch = get_settings().clickhouse
    client = clickhouse_connect.get_client(
        host=ch.host,
        port=ch.port,
        username=ch.user,
        password=ch.password,
        database=ch.database,
    )
    sql_dir = pathlib.Path(__file__).resolve().parents[2] / "clickhouse"
    applied = apply_clickhouse_schema(client, sql_dir)
    print("clickhouse applied:", ", ".join(applied) or "(none)")


def createkey() -> None:
    parser = argparse.ArgumentParser(description="Create a gardevoir API key")
    parser.add_argument("--name", required=True)
    parser.add_argument("--upstream-base-url", default="https://api.openai.com/v1")
    parser.add_argument(
        "--upstream-api-key",
        default="",
        help="proxy 스코프에만 필요하다. admin 전용 키는 이 값을 쓸 수 없으므로 "
        "요구하지 않는다 — 쓰지도 못하는 프로바이더 시크릿을 함께 저장하면 "
        "컨트롤 플레인 크레덴셜 유출 시 피해 범위만 넓어진다.",
    )
    parser.add_argument(
        "--guardrail",
        action="append",
        default=None,
        help="반복 지정 가능. 첫 번째가 기본 가드레일이 된다. 생략하면 base.",
    )
    parser.add_argument(
        "--scope",
        action="append",
        choices=[str(s) for s in Scope],
        default=None,
        help="반복 지정 가능. 생략하면 proxy 만 부여된다.",
    )
    args = parser.parse_args()
    scopes = args.scope or [str(Scope.PROXY)]
    if str(Scope.PROXY) in scopes and not args.upstream_api_key:
        parser.error("--upstream-api-key is required for a proxy-scoped key")
    print(asyncio.run(_run(args, args.guardrail or ["base"])))


async def _run(args: argparse.Namespace, guardrails: list[str]) -> str:
    factory = get_session_factory(get_settings().database.dsn)
    try:
        async with factory() as session:
            raw = await create_key(
                session=session,
                name=args.name,
                upstream_base_url=args.upstream_base_url,
                upstream_api_key=args.upstream_api_key,
                allowed_guardrails=guardrails,
                default_guardrail=guardrails[0],
                scopes=args.scope,
            )
            await session.commit()
    finally:
        await dispose_engine()
    return raw
