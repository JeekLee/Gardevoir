"""ApiKey input DTOs."""

from pydantic import Field

from gateway.identity.domain.models.api_key import Scope
from shared_kernel.api import CamelModel


class CreateApiKey(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    upstream_base_url: str = Field(default="https://api.openai.com/v1", max_length=512)
    #: 프로바이더 시크릿. proxy 스코프에만 필요하다 — admin 전용 키는 업스트림을
    #: 부르지 않으므로, 쓰지도 못하는 시크릿을 같이 저장하면 컨트롤 플레인 크레덴셜이
    #: 새었을 때 피해 범위만 넓어진다.
    upstream_api_key: str = Field(default="", max_length=512)
    allowed_guardrails: list[str] = Field(default_factory=list)
    default_guardrail: str | None = None
    scopes: list[Scope] = Field(default_factory=lambda: [Scope.PROXY])
