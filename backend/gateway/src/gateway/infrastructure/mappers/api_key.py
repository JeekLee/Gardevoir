"""ApiKey domain <-> ORM mapping."""

from gateway.domain.models.api_key import ApiKey
from gateway.infrastructure.models.api_key import ApiKeyModel


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
    )
