from pydantic import AwareDatetime, Field

from shared_kernel.api import CamelModel


class CreateApiKey(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    #: 미래 시각만 허용한다 (도메인이 재확인). 순진한 naive datetime 은 422 로 떨군다.
    expires_at: AwareDatetime | None = None


class UpdateApiKey(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    expires_at: AwareDatetime | None = None
