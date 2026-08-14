"""ApiKey domain <-> ORM mapping."""

from gateway.identity.domain.api_key import ApiKey, Scope
from gateway.identity.infrastructure.api_key_model import ApiKeyModel


def to_domain(row: ApiKeyModel) -> ApiKey:
    return ApiKey(
        id=row.id,
        name=row.name,
        key_hash=row.key_hash,
        upstream_base_url=row.upstream_base_url,
        upstream_api_key=row.upstream_api_key,
        # jsonb comes back as a list; the aggregate is immutable.
        allowed_guardrails=tuple(row.allowed_guardrails or ()),
        default_guardrail=row.default_guardrail,
        disabled=row.disabled,
        # jsonb 는 list 로 돌아온다. 알 수 없는 스코프 문자열은 버린다 —
        # 기본값을 안전한 쪽으로 두는 원칙대로, 오타가 권한을 주지 않는다.
        scopes=tuple(Scope(s) for s in (row.scopes or []) if s in set(Scope)) or (Scope.PROXY,),
    )


def to_model(key: ApiKey) -> ApiKeyModel:
    return ApiKeyModel(
        id=key.id,
        name=key.name,
        key_hash=key.key_hash,
        upstream_base_url=key.upstream_base_url,
        upstream_api_key=key.upstream_api_key,
        allowed_guardrails=list(key.allowed_guardrails),
        default_guardrail=key.default_guardrail,
        disabled=key.disabled,
        scopes=[str(s) for s in key.scopes],
    )
