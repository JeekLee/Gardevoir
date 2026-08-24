from datetime import datetime
from uuid import UUID

from shared_kernel.api import CamelModel


class ProviderSummary(CamelModel):
    """api_key(공급자 비밀)는 프로젝션하지 않는다."""

    id: UUID
    name: str
    base_url: str
    models: list[str]
    #: 키가 설정돼 있는지만 노출한다 — 값은 절대 아니다.
    has_api_key: bool
    created_at: datetime
    updated_at: datetime
