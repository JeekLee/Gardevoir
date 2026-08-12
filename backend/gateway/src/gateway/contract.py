"""The wire contract between gardevoir and client applications.

프로토콜은 최소로 유지한다. 여기에 항목을 추가하는 것은 배포된 앱을 깨뜨릴 수 있는
되돌리기 어려운 결정이다. 가변적인 것은 설정으로 뺀다 (§7).

이 모듈은 gateway가 소유한다. shared_kernel이 와이어 계약을 가지면 계약 변경이
모든 바운디드 컨텍스트를 흔든다.
"""

from enum import StrEnum

HEADER_GUARDRAIL = "X-Gardevoir-Guardrail"
HEADER_MODE = "X-Gardevoir-Mode"
HEADER_ACTION = "X-Gardevoir-Action"
HEADER_GUARDRAIL_VERSION = "X-Gardevoir-Guardrail-Version"
HEADER_AUDIT_ID = "X-Gardevoir-Audit-Id"
HEADER_LATENCY_MS = "X-Gardevoir-Latency-Ms"
HEADER_REQUEST_ID = "X-Request-Id"

EXTENSION_KEY = "gardevoir"

#: 계약 버전은 URL 접두어가 담당한다. 헤더를 두면 호출처가 관리해야 하는데
#: 그건 쓸모없는 부담이다 (§7.2).
API_PREFIX = "/v1"

#: OpenAI SDK가 Literal로 검증하는 값들. 이 밖의 값은 클라이언트를 깨뜨린다 (§11.9).
STANDARD_FINISH_REASONS = frozenset(
    {"stop", "length", "tool_calls", "content_filter", "function_call"}
)

#: Phase 1에는 컴파일된 가드레일이 없다. Phase 2에서 실제 발행 버전이 들어간다.
UNVERSIONED_GUARDRAIL = 0


class Action(StrEnum):
    ALLOW = "allow"
    BLOCKED = "blocked"
    APPROVAL_REQUIRED = "approval_required"


class Mode(StrEnum):
    ENFORCE = "enforce"
    DRY_RUN = "dry-run"

    @classmethod
    def parse(cls, raw: str | None) -> "Mode":
        """Unknown or missing values fall back to enforce — never fail open."""
        if not raw:
            return cls.ENFORCE
        try:
            return cls(raw.strip().lower())
        except ValueError:
            return cls.ENFORCE


def build_extension(
    *,
    action: Action,
    guardrail: str,
    guardrail_version: int,
    audit_id: str,
    mode: Mode,
    dry_run_would_have: dict | None = None,
) -> dict:
    """Build the top-level `gardevoir` object attached to a response body."""
    ext: dict = {
        "action": str(action),
        "guardrail": guardrail,
        "guardrail_version": guardrail_version,
        "mode": str(mode),
        "audit_id": audit_id,
    }
    if mode is Mode.DRY_RUN:
        ext["dry_run"] = True
        if dry_run_would_have is not None:
            ext["would_have"] = dry_run_would_have
    return ext


def response_headers(
    *,
    action: Action,
    guardrail: str,
    guardrail_version: int,
    mode: Mode,
    audit_id: str,
    latency_ms: float,
) -> dict[str, str]:
    """Headers echoed on every proxied response.

    Guardrail and mode are echoed so a caller can detect that its requested
    values were overridden — without that, an app that asked for dry-run and
    was silently enforced would believe it had tested safely (§7.2).
    """
    return {
        HEADER_ACTION: str(action),
        HEADER_GUARDRAIL: guardrail,
        HEADER_GUARDRAIL_VERSION: str(guardrail_version),
        HEADER_MODE: str(mode),
        HEADER_AUDIT_ID: audit_id,
        HEADER_LATENCY_MS: f"{latency_ms:.3f}",
    }
