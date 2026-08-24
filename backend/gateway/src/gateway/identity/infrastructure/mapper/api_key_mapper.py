from gateway.identity.domain.models.api_key import ApiKey
from gateway.identity.infrastructure.model.api_key_model import ApiKeyModel


def to_domain(row: ApiKeyModel) -> ApiKey:
    return ApiKey(
        id=row.id,
        name=row.name,
        key=row.key,
        user_id=row.user_id,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


def to_model(api_key: ApiKey) -> ApiKeyModel:
    return ApiKeyModel(
        id=api_key.id,
        name=api_key.name,
        key=api_key.key,
        user_id=api_key.user_id,
        expires_at=api_key.expires_at,
        revoked_at=api_key.revoked_at,
    )
