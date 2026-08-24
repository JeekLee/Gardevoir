from gateway.provider.domain.models.provider import Provider
from gateway.provider.infrastructure.model.provider_model import ProviderModel


def to_domain(row: ProviderModel) -> Provider:
    return Provider(
        id=row.id,
        name=row.name,
        base_url=row.base_url,
        api_key=row.api_key,
        models=tuple(row.models or ()),
    )


def to_model(provider: Provider) -> ProviderModel:
    return ProviderModel(
        id=provider.id,
        name=provider.name,
        base_url=provider.base_url,
        api_key=provider.api_key,
        models=list(provider.models),
    )
