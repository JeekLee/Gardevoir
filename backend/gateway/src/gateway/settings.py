"""Gateway settings.

Inherits the shared nested settings (database, clickhouse, log) and adds the
gateway's own knobs.
"""

from functools import lru_cache
from typing import Annotated, Literal

import orjson
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import NoDecode

from shared_kernel.config import BaseAppSettings


class ModelJudgeFailModeSettings(BaseModel):
    """Checkpoint-specific behavior when an enabled judge cannot decide."""

    input: Literal["open", "closed"] = "closed"
    tool_result: Literal["open", "closed"] = "closed"
    output: Literal["open", "closed"] = "open"
    tool_call: Literal["open", "closed"] = "closed"


class ModelJudgeSettings(BaseModel):
    """Shieldstral judgement endpoint settings."""

    enabled: bool = False
    #: ``/v1/chat/completions`` 까지 포함한 전체 URL. disabled 일 때는 비워도 된다.
    endpoint: str = ""
    model: str = "mistralai/Shieldstral-1.0-3B"
    #: 서빙 쪽에서 고정한 모델 revision. 요청 파라미터가 아니라 감사 식별자다.
    revision: str = ""
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    timeout_ms: int = Field(default=1_000, gt=0)
    max_images: int = Field(default=4, gt=0)
    max_data_uri_bytes: int = Field(default=5_242_880, gt=0)
    fail_mode: ModelJudgeFailModeSettings = Field(default_factory=ModelJudgeFailModeSettings)

    @field_validator("endpoint", "model", "revision")
    @classmethod
    def _strip_model_judge_strings(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _validate_enabled_endpoint(self) -> ModelJudgeSettings:
        if not self.model:
            raise ValueError("model must be a non-empty string")
        if self.enabled and not self.endpoint:
            raise ValueError("endpoint is required when model judge is enabled")
        if self.endpoint and not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("endpoint must be an http(s) URL")
        return self


class AuditSettings(BaseModel):
    """Audit content evidence controls (§10)."""

    excerpt_max_chars: int = Field(default=256, ge=32)


class GatewaySettings(BaseAppSettings):
    upstream_timeout_s: float = Field(default=120.0, gt=0)
    model_judge: ModelJudgeSettings = Field(default_factory=ModelJudgeSettings)
    audit: AuditSettings = Field(default_factory=AuditSettings)

    #: 기본값은 빈 목록이다. 운영 환경에서 설정 누락으로 개발 오리진이 열리는 것보다,
    #: 필요한 오리진을 배포 설정에 명시하게 하는 편이 안전하다.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    #: 요청 경로에 DB 접근이 없어야 하므로 키 조회를 인메모리로 덮는다 (§6).
    key_cache_ttl_s: float = Field(default=30.0, gt=0)

    #: 기동 시 admin 키가 하나도 없으면 이 값으로 하나 만든다. 비워두면 아무것도 안 한다.
    #:
    #: 순환을 끊는 유일한 장치다 — 관리 API 를 부르려면 admin 키가 필요한데, 키를
    #: 만드는 것이 그 관리 API 다. 운영자가 이미 아는 값을 심으므로 "원본이 한 번만
    #: 보인다"는 문제도 없다.
    #:
    #: **활성 admin 키가 이미 있으면 무시된다.** 환경변수가 남아 있다는 이유로 키가
    #: 되살아나면 회수가 성립하지 않는다.
    bootstrap_admin_key: str = ""

    #: 액세스 토큰 서명 키. 기본값을 두지 않는다 — 두면 그 값이 곧 취약점이다.
    #: RFC 7518 §3.2 가 HS256 에 최소 32바이트를 요구한다.
    jwt_secret: str = Field(min_length=32)
    access_token_ttl_s: int = Field(default=900, gt=0)
    refresh_token_ttl_s: int = Field(default=1_209_600, gt=0)

    #: 사용자가 하나도 없을 때만 이 값으로 루트 계정을 만든다. 둘 다 있어야 동작한다.
    root_email: str = ""
    root_password: str = ""

    audit_batch_size: int = Field(default=100, gt=0)
    audit_flush_interval_s: float = Field(default=1.0, gt=0)
    audit_queue_maxsize: int = Field(default=10_000, gt=0)

    #: 방출을 이만큼(문자) 늦춰 짧은 유출 패턴을 화면에 나가기 전에 잡는다 (§9).
    #:
    #: 단위가 문자인 이유: 우리에게 토크나이저가 없다. §9 의 "32토큰 = 640 ms 판정
    #: 예산"은 영어 ~4자/토큰 기준이라 128자에 해당한다. 한국어는 토큰이 더 적게
    #: 들어가므로 같은 문자 수가 더 보수적이다(지연 증가, 탐지 향상).
    #:
    #: 0 이어도 한 청크 안에서 완성된 패턴은 가려진다 — 검사가 방출보다 앞선다.
    #: 못 가리는 것은 앞 청크가 이미 나간 뒤에 패턴이 완성되는 경우다.
    stream_holdback_chars: int = Field(default=128, ge=0)

    #: 겹치는 검사 윈도우 크기 (§9). 직전 이만큼을 새 청크와 함께 다시 본다 —
    #: 누적 전체를 매 청크마다 스캔하면 O(n²) 이다. 512 는 실무 패턴 기준이다.
    stream_window_chars: int = Field(default=512, gt=0)

    #: 발행 전파 주기. uvicorn 워커는 별도 프로세스라 한 워커의 발행이 다른 워커에
    #: 보이지 않는다. §14 가 "LISTEN/NOTIFY 는 후속, 폴링으로 시작"이라고 했다.
    #: 사용자가 체감하는 것은 "발행 후 반영까지 이 주기"뿐이다.
    plan_poll_interval_s: float = Field(default=5.0, gt=0)

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_cors_allow_origins(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            return []
        if value.startswith("["):
            return orjson.loads(value)
        return [origin.strip() for origin in value.split(",") if origin.strip()]


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()  # type: ignore[call-arg]
