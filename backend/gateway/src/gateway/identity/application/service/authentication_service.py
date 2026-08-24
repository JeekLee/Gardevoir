"""프록시 크레덴셜 검증. 요청마다 Postgres 를 한 번 조회한다 (캐시 없음, §11).

스코프가 없다 — 유효한 키는 곧 프록시를 부를 수 있다는 뜻이다. 관리 API 인증은
사람 계정(JWT·Role)이 따로 담당한다 (shared_kernel.auth).

가드레일 선택은 여기 없다 — 그것은 프록시 계약(헤더)의 일이고, proxy 계층이 정한다.
"""

from gateway.identity.application.repository.api_key_repository import ApiKeyRepository
from gateway.identity.domain.exceptions.api_key_error import ApiKeyError
from gateway.identity.domain.models.api_key import ApiKey


class AuthenticationService:
    def __init__(self, *, api_key_repository: ApiKeyRepository) -> None:
        self._api_key_repository = api_key_repository

    async def authenticate(self, authorization: str | None) -> ApiKey:
        scheme, _, token = (authorization or "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            ApiKeyError.INVALID_KEY.raise_()
        key = await self._api_key_repository.find_by_key(token)
        if key is None:
            ApiKeyError.INVALID_KEY.raise_()
        key.ensure_active()
        return key


__all__ = ["AuthenticationService"]
