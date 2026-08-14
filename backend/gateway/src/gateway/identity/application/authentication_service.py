"""Authentication use case.

두 단계다. ``authorise`` 는 크레덴셜을 확인하고 스코프를 요구한다 — 모든 라우트가
쓴다. ``authenticate`` 는 그 위에 프록시 요청에만 있는 것(가드레일, 모드)을 얹는다.

둘을 가른 이유: 저작 API 는 해석할 가드레일이 없다. 한 메서드로 묶어 두면 admin
키에도 default_guardrail 을 억지로 넣어야 하고, 그러면 정책 관리용 키가 프록시
경로에서도 쓸 수 있는 무언가를 갖게 된다.
"""

from dataclasses import dataclass

from gateway.identity.application.api_key_repository import ApiKeyRepository
from gateway.identity.domain.api_key import ApiKey, Scope, hash_key, parse_bearer
from gateway.identity.domain.api_key_error import ApiKeyError


@dataclass(frozen=True, slots=True)
class AuthenticatedRequest:
    key: ApiKey
    guardrail: str


class AuthenticationService:
    def __init__(self, *, keys: ApiKeyRepository) -> None:
        self._keys = keys

    async def authorise(self, *, authorization: str | None, require: Scope) -> ApiKey:
        """Resolve the credential and demand a scope.

        require 에 기본값을 두지 않는다. 기본값이 PROXY 면 admin 라우트를
        추가하며 require 를 빼먹은 사람이 proxy 키로 admin 에 접근하게 된다 —
        안전한 기본값이 존재하지 않는 자리다. 호출자가 반드시 선언해야 한다.
        """
        raw = parse_bearer(authorization)
        if raw is None:
            # 헤더가 없거나 형식이 틀렸으면 조회할 이유가 없다.
            ApiKeyError.INVALID_KEY.raise_()

        # 원본 키는 리포지토리 경계를 넘지 않는다 — 로그나 쿼리에 남을 수 있다.
        key = await self._keys.find_by_hash(hash_key(raw))
        if key is None:
            ApiKeyError.INVALID_KEY.raise_()

        key.require_scope(require)
        return key

    async def authenticate(
        self,
        *,
        authorization: str | None,
        guardrail: str | None,
        require: Scope,
    ) -> AuthenticatedRequest:
        # 스코프는 가드레일 해석보다 먼저 본다 — 권한이 없으면 그 키가 어떤
        # 가드레일을 쓸 수 있는지 알려줄 이유가 없다.
        key = await self.authorise(authorization=authorization, require=require)

        return AuthenticatedRequest(key=key, guardrail=key.resolve_guardrail(guardrail))
