import pytest

from gateway.application.service.authentication_service import AuthenticationService
from gateway.contract import Mode
from gateway.domain.models.api_key import ApiKey, Scope, generate_key, hash_key
from shared_kernel.exception import ForbiddenError, UnauthorizedError


class StubRepository:
    def __init__(self, keys: dict[str, ApiKey] | None = None) -> None:
        self.keys = keys or {}
        self.lookups: list[str] = []

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        self.lookups.append(key_hash)
        return self.keys.get(key_hash)

    async def add(self, key: ApiKey) -> None:
        self.keys[key.key_hash] = key


def _service(raw: str | None = None, **kw) -> tuple[AuthenticationService, StubRepository]:
    keys: dict[str, ApiKey] = {}
    if raw is not None:
        fields: dict = {
            "id": "k1",
            "name": "app",
            "key_hash": hash_key(raw),
            "upstream_base_url": "https://api.openai.com/v1",
            "upstream_api_key": "sk-upstream",
            "allowed_guardrails": ("base", "doc-agent"),
            "default_guardrail": "base",
        }
        fields.update(kw)
        keys[hash_key(raw)] = ApiKey(**fields)
    repo = StubRepository(keys)
    return AuthenticationService(keys=repo), repo


async def test_authenticates_and_resolves_defaults():
    raw = generate_key()
    service, _ = _service(raw)
    result = await service.authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.PROXY
    )
    assert result.key.id == "k1"
    assert result.guardrail == "base"
    assert result.mode is Mode.ENFORCE


async def test_lookup_uses_the_hash_not_the_raw_key():
    """원본 키가 리포지토리 경계를 넘으면 로그·쿼리에 남을 수 있다."""
    raw = generate_key()
    service, repo = _service(raw)
    await service.authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.PROXY
    )
    assert repo.lookups == [hash_key(raw)]
    assert raw not in repo.lookups


async def test_missing_authorization_is_401():
    service, repo = _service()
    with pytest.raises(UnauthorizedError) as info:
        await service.authenticate(
            authorization=None, guardrail=None, mode=None, require=Scope.PROXY
        )
    assert info.value.code == "APIKEY-001"
    # 헤더가 없으면 DB를 때릴 이유가 없다
    assert repo.lookups == []


async def test_malformed_authorization_is_401():
    service, _ = _service()
    with pytest.raises(UnauthorizedError):
        await service.authenticate(
            authorization="Basic abc", guardrail=None, mode=None, require=Scope.PROXY
        )


async def test_unknown_key_is_401():
    service, _ = _service()
    with pytest.raises(UnauthorizedError) as info:
        await service.authenticate(
            authorization=f"Bearer {generate_key()}",
            guardrail=None,
            mode=None,
            require=Scope.PROXY,
        )
    assert info.value.code == "APIKEY-001"


async def test_error_does_not_echo_the_key():
    """401 응답이나 로그에 크레덴셜이 실려서는 안 된다."""
    raw = generate_key()
    service, _ = _service()
    with pytest.raises(UnauthorizedError) as info:
        await service.authenticate(
            authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.PROXY
        )
    assert raw not in str(info.value)
    assert raw not in str(info.value.details or "")


async def test_unallowed_guardrail_is_403():
    raw = generate_key()
    service, _ = _service(raw)
    with pytest.raises(ForbiddenError) as info:
        await service.authenticate(
            authorization=f"Bearer {raw}",
            guardrail="internal-analytics",
            mode=None,
            require=Scope.PROXY,
        )
    assert info.value.code == "APIKEY-002"


async def test_allowed_guardrail_is_honoured():
    raw = generate_key()
    service, _ = _service(raw)
    result = await service.authenticate(
        authorization=f"Bearer {raw}",
        guardrail="doc-agent",
        mode=None,
        require=Scope.PROXY,
    )
    assert result.guardrail == "doc-agent"


async def test_dry_run_is_accepted_without_a_permission_check():
    """모드는 자유 선택이다 — 공격자는 헤더를 만지지 못하고 대화 텍스트만 통제한다."""
    raw = generate_key()
    service, _ = _service(raw)
    result = await service.authenticate(
        authorization=f"Bearer {raw}",
        guardrail=None,
        mode="dry-run",
        require=Scope.PROXY,
    )
    assert result.mode is Mode.DRY_RUN


async def test_unknown_mode_falls_back_to_enforce():
    raw = generate_key()
    service, _ = _service(raw)
    result = await service.authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode="off", require=Scope.PROXY
    )
    assert result.mode is Mode.ENFORCE


async def test_disabled_key_never_reaches_the_service():
    """비활성 필터는 리포지토리가 담당한다. 서비스는 None 을 401 로 바꾼다."""
    raw = generate_key()
    service, _ = _service()  # 리포지토리가 비어 있는 상황 = 비활성/미등록
    with pytest.raises(UnauthorizedError):
        await service.authenticate(
            authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.PROXY
        )


async def test_result_is_immutable():
    raw = generate_key()
    service, _ = _service(raw)
    result = await service.authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.PROXY
    )
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.guardrail = "other"  # type: ignore[misc]


# --- 스코프 인가 -------------------------------------------------------------


async def test_default_key_may_use_the_proxy():
    from gateway.domain.models.api_key import Scope

    raw = generate_key()
    service, _ = _service(raw)
    result = await service.authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.PROXY
    )
    assert result.key.id == "k1"


async def test_default_key_cannot_reach_admin():
    """기본 스코프는 proxy 뿐이다 — 오타나 누락이 권한을 주면 안 된다."""
    from gateway.domain.models.api_key import Scope

    raw = generate_key()
    service, _ = _service(raw)
    with pytest.raises(ForbiddenError) as info:
        await service.authenticate(
            authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.ADMIN
        )
    assert info.value.code == "APIKEY-005"


async def test_admin_scoped_key_reaches_admin():
    from gateway.domain.models.api_key import Scope

    raw = generate_key()
    service, _ = _service(raw, scopes=(Scope.PROXY, Scope.ADMIN))
    result = await service.authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.ADMIN
    )
    assert result.key.has_scope(Scope.ADMIN)


async def test_scope_is_checked_before_guardrail_resolution():
    """권한이 없으면 그 키가 어떤 가드레일을 쓸 수 있는지 알려줄 이유가 없다."""
    from gateway.domain.models.api_key import Scope

    raw = generate_key()
    service, _ = _service(raw)
    with pytest.raises(ForbiddenError) as info:
        await service.authenticate(
            authorization=f"Bearer {raw}",
            guardrail="internal-analytics",  # 허용되지 않은 가드레일
            mode=None,
            require=Scope.ADMIN,  # 그런데 스코프도 없다
        )
    # 스코프 오류가 먼저 나야 한다
    assert info.value.code == "APIKEY-005"


async def test_require_has_no_default():
    """기본값이 있으면 admin 라우트에서 require 를 빼먹은 사람이 proxy 키로
    admin 에 접근하게 된다. 안전한 기본값이 존재하지 않는 자리다."""
    raw = generate_key()
    service, _ = _service(raw)
    with pytest.raises(TypeError):
        await service.authenticate(authorization=f"Bearer {raw}", guardrail=None, mode=None)


# --- authorise: 크레덴셜만 확인하는 단계 --------------------------------------


async def test_authorise_returns_the_key_without_resolving_a_guardrail():
    """저작 API 에는 해석할 가드레일이 없다."""
    raw = generate_key()
    service, _ = _service(raw, allowed_guardrails=(), default_guardrail=None, scopes=(Scope.ADMIN,))
    key = await service.authorise(authorization=f"Bearer {raw}", require=Scope.ADMIN)
    assert key.id == "k1"


async def test_authorise_still_demands_the_scope():
    raw = generate_key()
    service, _ = _service(raw)  # 기본 스코프 = proxy
    with pytest.raises(ForbiddenError) as info:
        await service.authorise(authorization=f"Bearer {raw}", require=Scope.ADMIN)
    assert info.value.code == "APIKEY-005"


async def test_authorise_rejects_a_missing_header_without_a_lookup():
    service, repo = _service()
    with pytest.raises(UnauthorizedError):
        await service.authorise(authorization=None, require=Scope.ADMIN)
    assert repo.lookups == []


async def test_authorise_rejects_an_unknown_key():
    service, _ = _service()
    with pytest.raises(UnauthorizedError) as info:
        await service.authorise(authorization=f"Bearer {generate_key()}", require=Scope.ADMIN)
    assert info.value.code == "APIKEY-001"


async def test_authorise_requires_the_scope_argument():
    """기본값이 있으면 라우트를 추가하며 빼먹은 사람이 권한을 얻는다."""
    raw = generate_key()
    service, _ = _service(raw)
    with pytest.raises(TypeError):
        await service.authorise(authorization=f"Bearer {raw}")  # type: ignore[call-arg]


async def test_an_admin_only_key_cannot_authenticate_for_the_proxy():
    raw = generate_key()
    service, _ = _service(raw, scopes=(Scope.ADMIN,))
    with pytest.raises(ForbiddenError) as info:
        await service.authenticate(
            authorization=f"Bearer {raw}", guardrail=None, mode=None, require=Scope.PROXY
        )
    assert info.value.code == "APIKEY-005"
