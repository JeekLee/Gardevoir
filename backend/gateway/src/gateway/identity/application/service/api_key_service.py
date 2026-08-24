"""API key 관리 — 로그인 사용자가 자기 키를 발급·수정·회수·목록한다."""

import logging
from uuid import UUID

from gateway.identity.application.command.api_key_command import CreateApiKey, UpdateApiKey
from gateway.identity.application.dao.api_key_dao import ApiKeyDao
from gateway.identity.application.repository.api_key_repository import ApiKeyRepository
from gateway.identity.application.result.api_key_result import ApiKeyCreated, ApiKeySummary
from gateway.identity.domain.exceptions.api_key_error import ApiKeyError
from gateway.identity.domain.models.api_key import ApiKey
from shared_kernel.api import Page
from shared_kernel.database import UnitOfWork

logger = logging.getLogger(__name__)


class ApiKeyService:
    def __init__(
        self,
        *,
        api_key_repository: ApiKeyRepository,
        api_key_dao: ApiKeyDao,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._api_key_repository = api_key_repository
        self._api_key_dao = api_key_dao
        self._unit_of_work = unit_of_work

    async def create(self, user_id: UUID, cmd: CreateApiKey) -> ApiKeyCreated:
        # 발급 전에 키를 만든다 — 원본은 이 응답에만 실린다.
        key = ApiKey.issue(name=cmd.name, user_id=user_id, expires_at=cmd.expires_at)
        async with self._unit_of_work:
            if await self._api_key_dao.exists_for_user_with_name(user_id, cmd.name):
                ApiKeyError.DUPLICATE_NAME.raise_(details={"name": cmd.name})
            await self._api_key_repository.add(key)
        logger.info("api key %r issued for user %s", key.name, user_id)
        return ApiKeyCreated(id=key.id, name=key.name, key=key.key, expires_at=key.expires_at)

    async def list(self, user_id: UUID) -> Page[ApiKeySummary]:
        items, total = await self._api_key_dao.list_for_user(user_id)
        return Page(items=items, total=total)

    async def update(self, user_id: UUID, api_key_id: UUID, cmd: UpdateApiKey) -> ApiKeySummary:
        key = await self._owned(user_id, api_key_id)
        async with self._unit_of_work:
            await self._api_key_repository.save(
                key.update(name=cmd.name, expires_at=cmd.expires_at)
            )
            return await self._summary(api_key_id)

    async def revoke(self, user_id: UUID, api_key_id: UUID) -> None:
        key = await self._owned(user_id, api_key_id)
        async with self._unit_of_work:
            await self._api_key_repository.save(key.revoke())

    async def _owned(self, user_id: UUID, api_key_id: UUID) -> ApiKey:
        """소유자 확인. 남의 키는 '없는 키' 로 답한다 — 존재 여부를 노출하지 않는다."""
        key = await self._api_key_repository.get(api_key_id)
        if key is None or key.user_id != user_id:
            ApiKeyError.NOT_FOUND.raise_(details={"id": str(api_key_id)})
        return key

    async def _summary(self, api_key_id: UUID) -> ApiKeySummary:
        summary = await self._api_key_dao.get_summary(api_key_id)
        assert summary is not None
        return summary


__all__ = ["ApiKeyService"]
