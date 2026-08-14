"""ApiKey write interface.

Repository operates on the domain aggregate. A read projection that returns a
result DTO would be a Dao — there is no read surface until the admin API in
Phase 2 (§5).
"""

from typing import Protocol

from gateway.identity.domain.api_key import ApiKey


class ApiKeyRepository(Protocol):
    async def find_by_hash(self, key_hash: str) -> ApiKey | None: ...

    async def add(self, key: ApiKey) -> None: ...
