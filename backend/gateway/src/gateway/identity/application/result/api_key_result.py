from datetime import datetime
from uuid import UUID

from shared_kernel.api import CamelModel


class ApiKeySummary(CamelModel):
    id: UUID
    name: str
    #: 원본이 아니라 미리보기(prefix…last4). 목록 응답·로그에 전체 키가 splash 되지 않게.
    key_preview: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApiKeyCreated(CamelModel):
    """발급 응답에만 원본 키가 실린다."""

    id: UUID
    name: str
    key: str
    expires_at: datetime | None
