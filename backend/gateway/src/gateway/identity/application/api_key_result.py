"""ApiKey read models.

**원본 키도 해시도 나가지 않는다.** 해시는 조회 키라서 그것만으로 인증을 흉내낼 수는
없지만, 목록 응답에 실을 이유가 없다. 업스트림 프로바이더 시크릿
(``upstream_api_key``)은 더더욱 나가면 안 된다 — 보유 여부만 알린다.
"""

from datetime import datetime

from gateway.identity.domain.models.api_key import Scope
from shared_kernel.api import CamelModel


class ApiKeySummary(CamelModel):
    id: str
    name: str
    upstream_base_url: str
    #: 값이 아니라 보유 여부만.
    has_upstream_key: bool
    allowed_guardrails: list[str]
    default_guardrail: str | None
    scopes: list[Scope]
    disabled: bool
    created_at: datetime
    updated_at: datetime


class ApiKeyCreated(CamelModel):
    """생성 응답 — 원본 키가 보이는 **유일한** 순간이다.

    저장되는 것은 sha256 해시뿐이므로 이 값을 잃으면 복구할 수 없고, 키를 다시
    만들어야 한다.
    """

    key: str
    api_key: ApiKeySummary
