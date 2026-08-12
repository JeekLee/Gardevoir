"""Gateway settings.

Inherits the shared nested settings (database, clickhouse, log) and adds the
gateway's own knobs.
"""

from functools import lru_cache

from pydantic import Field

from shared_kernel.config import BaseAppSettings


class GatewaySettings(BaseAppSettings):
    upstream_timeout_s: float = Field(default=120.0, gt=0)

    #: 요청 경로에 DB 접근이 없어야 하므로 키 조회를 인메모리로 덮는다 (§6).
    key_cache_ttl_s: float = Field(default=30.0, gt=0)

    audit_batch_size: int = Field(default=100, gt=0)
    audit_flush_interval_s: float = Field(default=1.0, gt=0)
    audit_queue_maxsize: int = Field(default=10_000, gt=0)

    #: 방출을 이만큼 늦춰 짧은 유출 패턴을 화면에 나가기 전에 잡는다 (§9).
    #: 0이면 즉시 방출(사후 검출)이 된다.
    stream_holdback_tokens: int = Field(default=32, ge=0)


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()  # type: ignore[call-arg]
