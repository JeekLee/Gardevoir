"""ApiKey management use cases.

CLI 가 아니라 여기에 있다. 발급 경로가 둘(운영자 셸, 관리 API)이면 검증도 둘이 되고,
한쪽에만 규칙을 더하는 사고가 난다. 부트스트랩 시딩도 이 서비스를 쓴다.

**원본 키는 이 클래스 밖으로 한 번만 나간다.** 저장되는 것은 sha256 해시뿐이라
(§7.2) 생성 응답을 잃으면 복구할 방법이 없다.
"""

import logging

from ulid import ULID

from gateway.identity.application.api_key_command import CreateApiKey
from gateway.identity.application.api_key_dao import ApiKeyDao
from gateway.identity.application.api_key_repository import ApiKeyRepository
from gateway.identity.application.api_key_result import ApiKeyCreated, ApiKeySummary
from gateway.identity.domain.api_key import ApiKey, Scope, generate_key, hash_key
from gateway.identity.domain.api_key_error import ApiKeyError
from shared_kernel.api import Page

logger = logging.getLogger(__name__)


class Transaction:
    """Structural type — commit() 를 가진 무엇이든."""

    async def commit(self) -> None: ...  # pragma: no cover - typing only


class ApiKeyService:
    def __init__(
        self,
        *,
        keys: ApiKeyRepository,
        dao: ApiKeyDao,
        transaction: Transaction | None = None,
    ) -> None:
        self._keys = keys
        self._dao = dao
        self._transaction = transaction

    async def create(self, cmd: CreateApiKey) -> ApiKeyCreated:
        scopes = tuple(cmd.scopes) or (Scope.PROXY,)
        if Scope.PROXY in scopes and not cmd.upstream_api_key:
            # 업스트림 크레덴셜이 없는 proxy 키는 첫 요청에서 실패한다. 발급 시점에
            # 막는 편이 낫다 — 그때는 무엇이 빠졌는지 말해 줄 수 있다.
            ApiKeyError.UPSTREAM_KEY_REQUIRED.raise_(details={"name": cmd.name})
        if await self._dao.exists_with_name(cmd.name):
            ApiKeyError.DUPLICATE_NAME.raise_(details={"name": cmd.name})

        raw = generate_key()
        guardrails = tuple(cmd.allowed_guardrails)
        key = ApiKey(
            id=str(ULID()),
            name=cmd.name,
            key_hash=hash_key(raw),
            upstream_base_url=cmd.upstream_base_url,
            upstream_api_key=cmd.upstream_api_key,
            allowed_guardrails=guardrails,
            # 첫 번째가 기본값이다. 목록이 비면 기본값도 없다 — resolve_guardrail 이
            # 그때 NO_GUARDRAIL_CONFIGURED 로 막는다.
            default_guardrail=cmd.default_guardrail or (guardrails[0] if guardrails else None),
            scopes=scopes,
        )
        await self._keys.add(key)
        summary = await self._dao.get_summary(key.id)
        await self._commit()
        assert summary is not None
        logger.info("api key %r created (scopes=%s)", key.name, [str(s) for s in scopes])
        return ApiKeyCreated(key=raw, api_key=summary)

    async def list(self) -> Page[ApiKeySummary]:
        items, total = await self._dao.list_summaries()
        return Page(items=items, total=total)

    async def set_disabled(self, key_id: str, *, disabled: bool) -> ApiKeySummary:
        if await self._keys.get(key_id) is None:
            ApiKeyError.NOT_FOUND.raise_(details={"id": key_id})
        await self._keys.set_disabled(key_id, disabled)
        summary = await self._dao.get_summary(key_id)
        await self._commit()
        assert summary is not None
        # 캐시 TTL 만큼은 이미 인증된 요청이 계속 통과한다 (§6 이 요청 경로에서 DB 를
        # 없애려고 받아들인 값이다). 회수가 즉시여야 하면 key_cache_ttl_s 를 줄인다.
        logger.info("api key %r disabled=%s", summary.name, disabled)
        return summary

    async def ensure_bootstrap_admin(self, raw_key: str, *, name: str = "bootstrap") -> bool:
        """admin 키가 하나도 없을 때만 주어진 원본 키로 하나 만든다.

        순환을 끊는 유일한 장치다 — 관리 API 를 부르려면 admin 키가 필요한데, 키를
        만드는 것이 그 관리 API 다. 운영자가 이미 아는 값을 심으므로 "한 번만 보이는"
        문제도 없다.

        이미 admin 키가 있으면 아무것도 하지 않는다. 환경변수가 남아 있다는 이유로
        키가 계속 되살아나면 회수가 성립하지 않는다.
        """
        if await self._keys.has_scope(str(Scope.ADMIN)):
            return False
        await self._keys.add(
            ApiKey(
                id=str(ULID()),
                name=name,
                key_hash=hash_key(raw_key),
                upstream_base_url="",
                upstream_api_key="",
                allowed_guardrails=(),
                default_guardrail=None,
                scopes=(Scope.ADMIN,),
            )
        )
        await self._commit()
        logger.warning(
            "bootstrap admin key %r seeded from settings; create real keys and disable it", name
        )
        return True

    async def _commit(self) -> None:
        """Make the write durable **before the response goes out**.

        조립 루트의 yield 정리 코드에 맡기면 FastAPI 가 응답을 보낸 뒤에 커밋한다 —
        guardrail 쪽에서 실측으로 확인한 것과 같은 문제다.
        """
        if self._transaction is not None:
            await self._transaction.commit()


__all__ = ["ApiKeyService"]
