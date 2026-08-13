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

#: 컴파일된 가드레일이 없다는 표시 — 발행본이 없는 가드레일을 지정한 경우.
#: 통과시키되 이 값과 빈 ``inspected`` 로 그 사실이 응답에 드러난다.
UNVERSIONED_GUARDRAIL = 0

#: ①③ 차단 시 본문에 담는 사유. `content` 에 사유를 넣는 것이 필수다 — 많은 앱이
#: `finish_reason` 을 보지 않고 `content` 만 쓴다 (§7.3).
BLOCKED_MESSAGE = "이 요청은 정책상 차단되었습니다."

#: Azure OpenAI 가 정착시킨 표준 값. 의미가 우리 체크포인트에 그대로 맞는다 (§7.3).
FINISH_CONTENT_FILTER = "content_filter"


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
    inspected: tuple[str, ...] = (),
    checks: tuple[str, ...] = (),
    dry_run_would_have: dict | None = None,
) -> dict:
    """Build the top-level `gardevoir` object attached to a response body.

    ``inspected`` 는 **실제로 돌린** 체크포인트 목록이다. 검사하지 않은 것과 검사해서
    통과한 것은 다르다 — 스트리밍은 홀드백이 없어 출력을 못 보고(§9, Phase 4),
    발행본이 없는 가드레일은 아무것도 못 본다. 말하지 않으면 호출자는 검사된 줄
    알고, 그것이 조용한 fail-open 이다.

    목록 하나로 둔 이유: Phase 3/4 가 tool_result·tool_call 을 더할 때 형태가 바뀌지
    않는다. 계약에 항목을 추가하는 것은 되돌리기 어렵다 (§7).
    """
    ext: dict = {
        "action": str(action),
        "guardrail": guardrail,
        "guardrail_version": guardrail_version,
        "mode": str(mode),
        "audit_id": audit_id,
        "inspected": list(inspected),
        "checks": list(checks),
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


def blocked_input_body(*, extension: dict, reason: str = BLOCKED_MESSAGE) -> dict:
    """① 입력 차단 — HTTP 400 + ``error.code = content_filter`` (§7.3).

    입력이 막히면 업스트림 응답이 아예 없으므로 OpenAI 의 오류 형태를 쓴다.
    """
    return {
        "error": {
            "message": reason,
            "type": "invalid_request_error",
            "code": FINISH_CONTENT_FILTER,
            "param": None,
        },
        EXTENSION_KEY: extension,
    }


def blocked_output_body(*, extension: dict, reason: str = BLOCKED_MESSAGE) -> dict:
    """③ 출력 차단 — HTTP 200 + ``finish_reason = content_filter`` (§7.3).

    업스트림은 정상 응답했으므로 200 이다. 커스텀 finish_reason 은 SDK 의 Literal
    검증에 걸리므로 표준 값만 쓴다 (§11.9).
    """
    return {
        "choices": [
            {
                "index": 0,
                "finish_reason": FINISH_CONTENT_FILTER,
                "logprobs": None,
                "message": {"role": "assistant", "content": reason},
            }
        ],
        EXTENSION_KEY: extension,
    }
