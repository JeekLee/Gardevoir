"""ApiKey read interface.

비활성 키도 돌려준다. 리포지토리의 ``find_by_hash`` 는 인증 경로라 비활성을 걸러내지만,
관리 화면은 비활성 키를 **봐야** 다시 켜거나 지울 수 있다.
"""

from typing import Protocol

from gateway.identity.application.api_key_result import ApiKeySummary


class ApiKeyDao(Protocol):
    async def get_summary(self, key_id: str) -> ApiKeySummary | None: ...

    async def list_summaries(self) -> tuple[list[ApiKeySummary], int]: ...

    async def exists_with_name(self, name: str) -> bool: ...
