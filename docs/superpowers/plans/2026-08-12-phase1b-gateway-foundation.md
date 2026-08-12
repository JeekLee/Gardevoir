# Phase 1b: gateway BC 기반 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **REQUIRED READING:** `skills/gardevoir-be/SKILL.md` before any step.

**Goal:** gateway 바운디드 컨텍스트를 세워 키 인증까지 동작하는 FastAPI 앱을 만든다. 프록시 중계는 Phase 1c에서 얹는다.

**Architecture:** clic 레이어링(DDD + CQRS-lite)을 따른다 — `domain`은 순수, `application`이 port/repository Protocol과 DTO를 소유, `infrastructure`가 어댑터를 구현, `presentation`은 인프라를 임포트하지 않고, `composition.py`만 인프라 구현체와 `Depends`를 안다. 와이어 계약(`contract.py`)은 gateway가 자기 것으로 소유한다 — `shared_kernel`이 계약을 가지면 계약 변경이 모든 BC를 흔든다.

**Tech Stack:** shared-kernel · FastAPI 0.141.1 · SQLAlchemy 2.0.52 (async) · psycopg 3.3.4 (binary) · Alembic 1.19.1 · openai SDK 3.0.0 (dev, 계약 회귀 테스트용) · pytest · respx · ruff

**설계 문서:** `docs/superpowers/specs/2026-08-12-gardevoir-design.md`
**컨벤션:** `skills/gardevoir-be/SKILL.md`
**선행:** Phase 1a (merged, PR #1)

---

## Global Constraints

Phase 1a의 제약이 모두 유효하다. 추가로:

- **`uv sync`가 아니라 `uv sync --all-packages`.** 가상 워크스페이스 루트는 맨 `uv sync`로
  멤버를 **제거**하고, 그 상태에서도 `import`가 성공해 `AttributeError`로만 드러난다.
  BC 디렉토리에서는 `uv sync`만으로도 된다(멤버가 `shared-kernel`을 의존성으로 선언하므로).
- **`ORJSONResponse`를 쓰지 않는다.** FastAPI 0.141에서 폐기됐다.
  `Response(content=orjson.dumps(...), media_type="application/json")`을 쓴다.
  `FastAPIDeprecationWarning`은 pytest에서 에러로 승격한다.
- **제네릭은 PEP 695**(`class Page[T]`). `Generic[T]`는 ruff UP046에 걸린다.
- **컨테이너 헬스체크는 `127.0.0.1`**, `localhost` 금지. 헬스 판정에 `grep healthy` 금지.
- **돌연변이 테스트 전에 커밋한다.** `git checkout --`가 커밋하지 않은 수정도 되돌린다.
- 테스트를 쓸 때 **"이 코드를 지우면 어느 테스트가 실패하는가"** 를 자문한다.
  상수·속성 값만 단정하는 테스트는 그 값을 소비하는 배선을 검증하지 않는다.
- 설정 테스트는 `_env`(GARDEVOIR_ 전체 `delenv`) + `_env_file=None` 형태를 쓴다.
  주변 셸 변수나 `.env`가 남으면 개발자 기계에서만 깨진다.
- 테스트 함수 독스트링은 근거 진술이므로 한국어. 모듈·클래스 독스트링은 영어.
- 설계 문서 인용은 맨 `§N`.

### 레이어 의존 방향 (위반은 리뷰에서 반려)

```
domain          순수. SQLAlchemy·FastAPI·httpx 임포트 금지.
                shared_kernel.exception 카테고리만 허용 (ErrorCatalog용)
application     domain 의존. repository/dao/port Protocol, command/result DTO, service
infrastructure  application port 구현. SQLAlchemy·httpx·clickhouse-connect는 여기만
presentation    application + composition 의존. infrastructure 임포트 금지
composition.py  인프라 구현체 → 서비스를 Depends로 잇는 유일한 곳
```

---

## File Structure

```
backend/
├── pyproject.toml                       members 에 "gateway" 추가
└── gateway/
    ├── pyproject.toml
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py
    │   └── versions/                    autogenerate 산출물
    ├── src/gateway/
    │   ├── __init__.py
    │   ├── settings.py                  GatewaySettings(BaseAppSettings)
    │   ├── contract.py                  헤더·Action/Mode·gardevoir 확장 객체
    │   ├── composition.py               DI 조립 루트
    │   ├── domain/
    │   │   ├── __init__.py
    │   │   ├── models/
    │   │   │   ├── __init__.py
    │   │   │   └── api_key.py           ApiKey 애그리거트 + 가드레일 해석
    │   │   └── exception/
    │   │       ├── __init__.py
    │   │       └── api_key_error.py     ApiKeyError(ErrorCatalog)
    │   ├── application/
    │   │   ├── __init__.py
    │   │   ├── repository/
    │   │   │   ├── __init__.py
    │   │   │   └── api_key_repository.py   Protocol
    │   │   └── service/
    │   │       ├── __init__.py
    │   │       └── authentication_service.py
    │   ├── infrastructure/
    │   │   ├── __init__.py
    │   │   ├── engine.py                lazy engine/session factory
    │   │   ├── models/
    │   │   │   ├── __init__.py          모든 ORM 모델 re-export (metadata 등록)
    │   │   │   └── api_key.py
    │   │   ├── mappers/
    │   │   │   ├── __init__.py
    │   │   │   └── api_key.py
    │   │   └── repository/
    │   │       ├── __init__.py
    │   │       ├── api_key_repository.py        SqlAlchemyApiKeyRepository
    │   │       └── cached_api_key_repository.py TTL 캐시 데코레이터
    │   └── presentation/
    │       ├── __init__.py
    │       └── http/
    │           ├── __init__.py
    │           ├── app.py               create_app()
    │           └── health.py
    └── tests/
        ├── conftest.py
        ├── test_contract.py
        ├── test_api_key_domain.py
        ├── test_api_key_repository.py
        ├── test_cached_api_key_repository.py
        ├── test_authentication_service.py
        └── test_app.py
```

`gateway`는 **src 레이아웃**을 쓴다(`shared_kernel`과 다름). clic의 BC와 동일하다.

---

## Task 1: gateway 워크스페이스 멤버 + 설정

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/gateway/pyproject.toml`
- Create: `backend/gateway/src/gateway/__init__.py`
- Create: `backend/gateway/src/gateway/settings.py`
- Create: `backend/gateway/.env.example`
- Test: `backend/gateway/tests/test_settings.py`
- Test: `backend/gateway/tests/conftest.py`

**Interfaces:**
- Consumes: `shared_kernel.config.BaseAppSettings`
- Produces:
  - `gateway.settings.GatewaySettings(BaseAppSettings)` — `upstream_timeout_s: float = 120.0`,
    `key_cache_ttl_s: float = 30.0`, `audit_batch_size: int = 100`,
    `audit_flush_interval_s: float = 1.0`, `audit_queue_maxsize: int = 10_000`,
    `stream_holdback_tokens: int = 32`
  - `gateway.settings.get_settings() -> GatewaySettings` (`lru_cache`)

- [ ] **Step 1: 워크스페이스 루트에 멤버 추가**

`backend/pyproject.toml`의 members를 고친다:

```toml
[tool.uv.workspace]
members = ["shared_kernel", "gateway"]
```

`[tool.ruff.lint.isort]`의 `known-first-party`에는 이미 `"gateway"`가 있다 — 확인만 한다.

- [ ] **Step 2: `backend/gateway/pyproject.toml` 작성**

```toml
[project]
name = "gateway"
version = "0.1.0"
description = "gardevoir gateway BC: OpenAI-compatible guardrail proxy"
requires-python = ">=3.12"
dependencies = [
    "shared-kernel",
    "fastapi>=0.141.1",
    "uvicorn[standard]>=0.52.1",
    "httpx>=0.28.1",
    "orjson>=3.11.9",
    "sqlalchemy[asyncio]>=2.0.52",
    "alembic>=1.19.1",
    "psycopg[binary,pool]>=3.3.4",
    "clickhouse-connect>=1.7.0",
    "pydantic-settings>=2.3",
    "python-ulid>=3.0",
    "google-re2>=1.1",
]

[dependency-groups]
dev = [
    "pytest>=9.1.1",
    "pytest-asyncio>=1.0",
    "respx>=0.23.1",
    "openai>=3.0.0",
    "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gateway"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
filterwarnings = [
    "error::fastapi.exceptions.FastAPIDeprecationWarning",
    "error::DeprecationWarning:gateway",
]
```

`openai`는 dev 의존성이다 — 런타임에 쓰지 않고 계약 회귀 테스트(§11.9)와 Phase 1c의
E2E 테스트에만 쓴다. `google-re2`는 Phase 2에서 쓰지만 지금 선언해 잠금 파일에
고정한다.

- [ ] **Step 3: `.env.example` 작성**

```
GARDEVOIR_APP_NAME=gateway
GARDEVOIR_DATABASE__DSN=postgresql+psycopg://gardevoir:gardevoir@localhost:21010/gardevoir
GARDEVOIR_CLICKHOUSE__HOST=localhost
GARDEVOIR_CLICKHOUSE__PORT=21020
GARDEVOIR_CLICKHOUSE__USER=gardevoir
GARDEVOIR_CLICKHOUSE__PASSWORD=gardevoir
GARDEVOIR_CLICKHOUSE__DATABASE=gardevoir
GARDEVOIR_LOG__LEVEL=INFO
```

포트는 21010/21020이다 — `infra/envs/example/compose.env`와 맞춘다.

- [ ] **Step 4: 실패하는 테스트 작성**

`backend/gateway/tests/conftest.py`:

```python
import os

_DEFAULTS = {
    "GARDEVOIR_APP_NAME": "gateway",
    "GARDEVOIR_DATABASE__DSN": (
        "postgresql+psycopg://gardevoir:gardevoir@localhost:21010/gardevoir"
    ),
    "GARDEVOIR_CLICKHOUSE__HOST": "localhost",
    "GARDEVOIR_CLICKHOUSE__PORT": "21020",
    "GARDEVOIR_CLICKHOUSE__USER": "gardevoir",
    "GARDEVOIR_CLICKHOUSE__PASSWORD": "gardevoir",
    "GARDEVOIR_CLICKHOUSE__DATABASE": "gardevoir",
}

for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)
```

`backend/gateway/tests/test_settings.py`:

```python
import os

import pytest
from pydantic import ValidationError

from gateway.settings import GatewaySettings, get_settings


def _env(monkeypatch, **extra):
    """Give the test a clean, hermetic environment.

    개발자 셸의 GARDEVOIR_* 변수나 패키지에 놓인 .env 파일이 남아 있으면
    기본값 단정이 조용히 깨진다. 두 경로를 모두 차단한다.
    """
    for name in [k for k in os.environ if k.startswith("GARDEVOIR_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GARDEVOIR_APP_NAME", "gateway")
    monkeypatch.setenv("GARDEVOIR_DATABASE__DSN", "postgresql+psycopg://u:p@h:5432/d")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def _settings(**kwargs) -> GatewaySettings:
    return GatewaySettings(_env_file=None, **kwargs)


def test_gateway_defaults(monkeypatch):
    _env(monkeypatch)
    s = _settings()
    assert s.app_name == "gateway"
    assert s.upstream_timeout_s == 120.0
    assert s.key_cache_ttl_s == 30.0
    assert s.audit_batch_size == 100
    assert s.audit_flush_interval_s == 1.0
    assert s.audit_queue_maxsize == 10_000
    assert s.stream_holdback_tokens == 32


def test_inherits_shared_kernel_nested_settings(monkeypatch):
    _env(monkeypatch, GARDEVOIR_CLICKHOUSE__PORT="21020")
    s = _settings()
    assert s.clickhouse.port == 21020
    assert s.clickhouse.host == "localhost"
    assert s.log.level == "INFO"


def test_gateway_field_reads_prefixed_env(monkeypatch):
    _env(monkeypatch, GARDEVOIR_KEY_CACHE_TTL_S="5.5")
    assert _settings().key_cache_ttl_s == 5.5


def test_negative_holdback_is_rejected(monkeypatch):
    """홀드백이 음수면 스트리밍 방출 계산이 조용히 망가진다."""
    _env(monkeypatch, GARDEVOIR_STREAM_HOLDBACK_TOKENS="-1")
    with pytest.raises(ValidationError):
        _settings()


def test_get_settings_is_cached(monkeypatch):
    _env(monkeypatch)
    assert get_settings() is get_settings()
```

- [ ] **Step 5: 테스트 실패 확인**

```bash
cd backend && uv sync --all-packages
cd gateway && uv run pytest tests/test_settings.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.settings'`

- [ ] **Step 6: `settings.py` 구현**

`backend/gateway/src/gateway/__init__.py`:

```python
__all__ = ["__version__"]
__version__ = "0.1.0"
```

`backend/gateway/src/gateway/settings.py`:

```python
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
```

- [ ] **Step 7: 테스트 통과 확인**

```bash
cd backend/gateway && uv run pytest tests/test_settings.py -q && uv run ruff check && uv run ruff format --check
```

Expected: 5 passed

- [ ] **Step 8: 커밋**

```bash
git add backend/pyproject.toml backend/uv.lock backend/gateway
git commit -m "feat: gateway BC 워크스페이스 멤버와 설정

BaseAppSettings를 상속해 gateway 고유 노브를 더한다. 상한/하한을 Field로
검증한다 — 홀드백이 음수면 스트리밍 방출 계산이 조용히 망가진다."
```

---

## Task 2: 와이어 계약 + SDK 회귀 테스트

계약을 먼저 고정한다. §7의 원칙("프로토콜은 최소, 설정은 최대")대로 이 모듈은 작게
유지되고, 여기에 항목을 추가하는 것은 배포된 앱을 깨뜨릴 수 있는 결정임을 코드 위치로
표현한다. `shared_kernel`이 아니라 **gateway가 소유한다**.

**Files:**
- Create: `backend/gateway/src/gateway/contract.py`
- Test: `backend/gateway/tests/test_contract.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - 헤더 상수: `HEADER_GUARDRAIL`, `HEADER_MODE`, `HEADER_ACTION`,
    `HEADER_GUARDRAIL_VERSION`, `HEADER_AUDIT_ID`, `HEADER_LATENCY_MS`, `HEADER_REQUEST_ID`
  - `EXTENSION_KEY: str` = `"gardevoir"`, `API_PREFIX: str` = `"/v1"`
  - `class Action(StrEnum)`: `ALLOW`, `BLOCKED`, `APPROVAL_REQUIRED`
  - `class Mode(StrEnum)`: `ENFORCE`, `DRY_RUN`; `Mode.parse(raw: str | None) -> Mode`
  - `STANDARD_FINISH_REASONS: frozenset[str]`
  - `UNVERSIONED_GUARDRAIL: int` = `0`
  - `build_extension(*, action, guardrail, guardrail_version, audit_id, mode, dry_run_would_have=None) -> dict`
  - `response_headers(*, action, guardrail, guardrail_version, mode, audit_id, latency_ms) -> dict[str, str]`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/gateway/tests/test_contract.py`:

```python
import orjson
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from gateway.contract import (
    API_PREFIX,
    EXTENSION_KEY,
    HEADER_ACTION,
    HEADER_AUDIT_ID,
    HEADER_GUARDRAIL,
    HEADER_GUARDRAIL_VERSION,
    HEADER_LATENCY_MS,
    HEADER_MODE,
    HEADER_REQUEST_ID,
    STANDARD_FINISH_REASONS,
    Action,
    Mode,
    build_extension,
    response_headers,
)


def test_header_names_are_exact():
    assert HEADER_GUARDRAIL == "X-Gardevoir-Guardrail"
    assert HEADER_MODE == "X-Gardevoir-Mode"
    assert HEADER_ACTION == "X-Gardevoir-Action"
    assert HEADER_GUARDRAIL_VERSION == "X-Gardevoir-Guardrail-Version"
    assert HEADER_AUDIT_ID == "X-Gardevoir-Audit-Id"
    assert HEADER_LATENCY_MS == "X-Gardevoir-Latency-Ms"
    assert HEADER_REQUEST_ID == "X-Request-Id"
    assert EXTENSION_KEY == "gardevoir"
    assert API_PREFIX == "/v1"


def test_no_protocol_version_header_exists():
    """계약 버전은 URL 접두어(/v1)가 담당한다. 헤더를 두면 호출처가 관리해야 한다."""
    import gateway.contract as c

    assert not [n for n in dir(c) if "PROTOCOL" in n.upper()]


def test_mode_parse_never_fails_open(monkeypatch):
    assert Mode.parse(None) is Mode.ENFORCE
    assert Mode.parse("") is Mode.ENFORCE
    assert Mode.parse("enforce") is Mode.ENFORCE
    assert Mode.parse("dry-run") is Mode.DRY_RUN
    assert Mode.parse("DRY-RUN") is Mode.DRY_RUN
    assert Mode.parse("  dry-run  ") is Mode.DRY_RUN
    # 알 수 없는 값은 시행으로 떨어진다 — 우회 수단이 되어서는 안 된다
    assert Mode.parse("nonsense") is Mode.ENFORCE
    assert Mode.parse("off") is Mode.ENFORCE


def test_build_extension_shape():
    ext = build_extension(
        action=Action.ALLOW,
        guardrail="doc-agent",
        guardrail_version=0,
        audit_id="evt_1",
        mode=Mode.ENFORCE,
    )
    assert ext == {
        "action": "allow",
        "guardrail": "doc-agent",
        "guardrail_version": 0,
        "mode": "enforce",
        "audit_id": "evt_1",
    }


def test_build_extension_dry_run_reports_would_have():
    ext = build_extension(
        action=Action.ALLOW,
        guardrail="doc-agent",
        guardrail_version=3,
        audit_id="evt_2",
        mode=Mode.DRY_RUN,
        dry_run_would_have={"action": "blocked", "checks": ["kr-rrn"]},
    )
    assert ext["dry_run"] is True
    assert ext["would_have"] == {"action": "blocked", "checks": ["kr-rrn"]}


def test_enforce_mode_carries_no_dry_run_keys():
    ext = build_extension(
        action=Action.ALLOW,
        guardrail="base",
        guardrail_version=0,
        audit_id="evt_3",
        mode=Mode.ENFORCE,
        dry_run_would_have={"action": "blocked"},
    )
    assert "dry_run" not in ext
    assert "would_have" not in ext


def test_response_headers_are_all_strings():
    h = response_headers(
        action=Action.ALLOW,
        guardrail="doc-agent",
        guardrail_version=0,
        mode=Mode.ENFORCE,
        audit_id="evt_4",
        latency_ms=0.6183,
    )
    assert h[HEADER_ACTION] == "allow"
    assert h[HEADER_GUARDRAIL_VERSION] == "0"
    assert h[HEADER_LATENCY_MS] == "0.618"
    assert all(isinstance(v, str) for v in h.values())


def test_response_headers_echo_requested_values():
    """앱이 dry-run을 요청했는데 무시됐다는 것을 알 수 있어야 한다 (§7.2)."""
    h = response_headers(
        action=Action.ALLOW,
        guardrail="internal-analytics",
        guardrail_version=7,
        mode=Mode.DRY_RUN,
        audit_id="evt_5",
        latency_ms=1.0,
    )
    assert h[HEADER_GUARDRAIL] == "internal-analytics"
    assert h[HEADER_MODE] == "dry-run"


# --- §11.9 회귀 테스트: SDK 확장 필드 관용성 ---------------------------------
# OAS 스펙이 자주 바뀌므로 실측을 고정한다. SDK 버전을 올릴 때 관용성이
# 바뀌면 여기서 즉시 실패해야 한다.

_BASE_COMPLETION = {
    "id": "x",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "logprobs": None,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "send_email", "arguments": "{}"},
                    }
                ],
            },
        }
    ],
}


def test_sdk_tolerates_extension_object_on_completion():
    payload = dict(
        _BASE_COMPLETION,
        gardevoir={"action": "approval_required", "audit_id": "evt_6"},
    )
    parsed = ChatCompletion.model_validate(payload)
    assert parsed.gardevoir["action"] == "approval_required"


def test_sdk_tolerates_extension_object_on_chunk():
    chunk = {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "gpt-4o",
        "choices": [
            {"index": 0, "delta": {"content": "hi"}, "finish_reason": None, "logprobs": None}
        ],
        "gardevoir": {"action": "blocked", "guardrail_version": 37},
    }
    parsed = ChatCompletionChunk.model_validate(chunk)
    assert parsed.gardevoir["guardrail_version"] == 37


def test_sdk_rejects_custom_finish_reason():
    """커스텀 finish_reason은 SDK를 깨뜨린다. 표준 값만 써야 하는 근거."""
    payload = dict(_BASE_COMPLETION)
    payload["choices"] = [
        dict(_BASE_COMPLETION["choices"][0], finish_reason="guard_approval_required")
    ]
    with pytest.raises(Exception) as exc:
        ChatCompletion.model_validate(payload)
    assert "finish_reason" in str(exc.value)


def test_standard_finish_reasons_match_sdk_literal():
    assert STANDARD_FINISH_REASONS == frozenset(
        {"stop", "length", "tool_calls", "content_filter", "function_call"}
    )
    for reason in STANDARD_FINISH_REASONS:
        payload = dict(_BASE_COMPLETION)
        payload["choices"] = [dict(_BASE_COMPLETION["choices"][0], finish_reason=reason)]
        ChatCompletion.model_validate(payload)  # 예외가 나면 실패


def test_extension_survives_orjson_roundtrip():
    ext = build_extension(
        action=Action.BLOCKED,
        guardrail="base",
        guardrail_version=1,
        audit_id="evt_7",
        mode=Mode.ENFORCE,
    )
    payload = dict(_BASE_COMPLETION, **{EXTENSION_KEY: ext})
    restored = orjson.loads(orjson.dumps(payload))
    assert ChatCompletion.model_validate(restored).gardevoir["action"] == "blocked"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/gateway && uv run pytest tests/test_contract.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.contract'`

- [ ] **Step 3: `contract.py` 구현**

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd backend/gateway && uv run pytest tests/test_contract.py -q && uv run ruff check && uv run ruff format --check
```

Expected: 13 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/gateway
git commit -m "feat: gateway 와이어 계약과 SDK 확장 필드 회귀 테스트

헤더 이름, Action/Mode, gardevoir 확장 객체를 한 모듈에 고정한다.
계약은 gateway가 소유한다 — shared_kernel이 가지면 계약 변경이 모든 BC를 흔든다.

openai SDK 3.0.0의 관용성을 테스트로 박아 SDK 업그레이드 시 확장 필드가
깨지면 즉시 드러나게 한다. Mode.parse는 알 수 없는 값을 시행으로 떨어뜨린다 —
우회 수단이 되어서는 안 된다."
```

---

## Task 3: ApiKey 도메인 + 에러 카탈로그

**Files:**
- Create: `backend/gateway/src/gateway/domain/__init__.py`
- Create: `backend/gateway/src/gateway/domain/models/__init__.py`
- Create: `backend/gateway/src/gateway/domain/models/api_key.py`
- Create: `backend/gateway/src/gateway/domain/exception/__init__.py`
- Create: `backend/gateway/src/gateway/domain/exception/api_key_error.py`
- Test: `backend/gateway/tests/test_api_key_domain.py`

**Interfaces:**
- Consumes: `shared_kernel.exception.{ErrorCatalog, UnauthorizedError, ForbiddenError, ConflictError}`
- Produces:
  - `gateway.domain.models.api_key.KEY_PREFIX: str` = `"gdv_live_"`
  - `gateway.domain.models.api_key.ApiKey` — frozen dataclass:
    `id: str`, `name: str`, `key_hash: str`, `upstream_base_url: str`, `upstream_api_key: str`,
    `allowed_guardrails: tuple[str, ...]`, `default_guardrail: str | None`, `disabled: bool`
    - `resolve_guardrail(requested: str | None) -> str` — raises `ApiKeyError.GUARDRAIL_NOT_ALLOWED`
  - `gateway.domain.models.api_key.generate_key() -> str`
  - `gateway.domain.models.api_key.hash_key(raw: str) -> str`
  - `gateway.domain.models.api_key.parse_bearer(header: str | None) -> str | None`
  - `gateway.domain.exception.api_key_error.ApiKeyError(ErrorCatalog)` —
    `INVALID_KEY`(401/`APIKEY-001`), `GUARDRAIL_NOT_ALLOWED`(403/`APIKEY-002`),
    `NO_GUARDRAIL_CONFIGURED`(403/`APIKEY-003`), `DUPLICATE_NAME`(409/`APIKEY-004`)

**도메인이 가드레일 해석을 소유하는 이유:** "요청이 키의 허용 집합을 벗어날 수 없다"는
것은 비즈니스 규칙이고 저장소나 전송과 무관하다 (§5, §7.2). 라우터나 리포지토리에 두면
같은 규칙이 여러 곳에 복제된다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/gateway/tests/test_api_key_domain.py`:

```python
import pytest
from shared_kernel.exception import ConflictError, ForbiddenError, UnauthorizedError

from gateway.domain.exception.api_key_error import ApiKeyError
from gateway.domain.models.api_key import (
    KEY_PREFIX,
    ApiKey,
    generate_key,
    hash_key,
    parse_bearer,
)


def _key(allowed=("base", "doc-agent"), default="base", **kw) -> ApiKey:
    fields = dict(
        id="k1",
        name="app",
        key_hash="deadbeef",
        upstream_base_url="https://api.openai.com/v1",
        upstream_api_key="sk-upstream",
        allowed_guardrails=allowed,
        default_guardrail=default,
        disabled=False,
    )
    fields.update(kw)
    return ApiKey(**fields)


def test_generate_key_has_prefix_and_entropy():
    k1, k2 = generate_key(), generate_key()
    assert k1.startswith(KEY_PREFIX)
    assert k1 != k2
    assert len(k1) > 40


def test_hash_key_is_stable_and_hides_the_key():
    raw = "gdv_live_abc"
    assert hash_key(raw) == hash_key(raw)
    assert hash_key(raw) != hash_key("gdv_live_abd")
    assert raw not in hash_key(raw)
    assert len(hash_key(raw)) == 64  # sha256 hex


def test_parse_bearer():
    assert parse_bearer("Bearer gdv_live_x") == "gdv_live_x"
    assert parse_bearer("bearer gdv_live_x") == "gdv_live_x"
    assert parse_bearer("Bearer   gdv_live_x  ") == "gdv_live_x"
    assert parse_bearer(None) is None
    assert parse_bearer("") is None
    assert parse_bearer("Basic abc") is None
    assert parse_bearer("Bearer") is None
    assert parse_bearer("Bearer ") is None


def test_resolve_guardrail_uses_default_when_absent():
    assert _key().resolve_guardrail(None) == "base"
    assert _key().resolve_guardrail("") == "base"


def test_resolve_guardrail_accepts_allowed():
    assert _key().resolve_guardrail("doc-agent") == "doc-agent"


def test_resolve_guardrail_rejects_unallowed():
    """앱이 허용 집합을 벗어날 수 없어야 한다 — 그래서 가드레일 선택이 키에 묶인다."""
    with pytest.raises(ForbiddenError) as info:
        _key().resolve_guardrail("internal-analytics")
    assert info.value.code == "APIKEY-002"
    assert info.value.details == {
        "requested": "internal-analytics",
        "allowed": ["base", "doc-agent"],
    }


def test_resolve_guardrail_falls_back_to_first_allowed_without_default():
    assert _key(default=None).resolve_guardrail(None) == "base"


def test_resolve_guardrail_fails_when_nothing_is_configured():
    with pytest.raises(ForbiddenError) as info:
        _key(allowed=(), default=None).resolve_guardrail(None)
    assert info.value.code == "APIKEY-003"


def test_api_key_is_immutable():
    """도메인 모델이 뒤에서 바뀌면 캐시된 인스턴스가 오염된다."""
    key = _key()
    with pytest.raises(Exception):
        key.name = "changed"  # type: ignore[misc]


def test_catalog_maps_each_error_to_its_category():
    assert isinstance(ApiKeyError.INVALID_KEY.exception(), UnauthorizedError)
    assert isinstance(ApiKeyError.GUARDRAIL_NOT_ALLOWED.exception(), ForbiddenError)
    assert isinstance(ApiKeyError.NO_GUARDRAIL_CONFIGURED.exception(), ForbiddenError)
    assert isinstance(ApiKeyError.DUPLICATE_NAME.exception(), ConflictError)


def test_catalog_codes_are_stable():
    """감사 로그와 클라이언트 처리에 쓰이므로 코드는 계약이다."""
    assert ApiKeyError.INVALID_KEY.code == "APIKEY-001"
    assert ApiKeyError.GUARDRAIL_NOT_ALLOWED.code == "APIKEY-002"
    assert ApiKeyError.NO_GUARDRAIL_CONFIGURED.code == "APIKEY-003"
    assert ApiKeyError.DUPLICATE_NAME.code == "APIKEY-004"


def test_domain_does_not_import_infrastructure():
    """domain은 순수해야 한다 (skills/gardevoir-be)."""
    import gateway.domain.models.api_key as mod

    source = open(mod.__file__).read()
    for forbidden in ("sqlalchemy", "fastapi", "httpx", "clickhouse"):
        assert forbidden not in source.lower()
```

> 마지막 테스트는 소스 텍스트를 단정하지만 예외적으로 허용한다 — 검증 대상이 코드의
> **동작**이 아니라 **의존 방향이라는 아키텍처 계약**이고, 임포트 부재는 실행으로는
> 관측할 수 없다. `AGENTS.md`의 테스트 원칙이 허용하는 "shipped artifact or contract"
> 경우에 해당한다.

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/gateway && uv run pytest tests/test_api_key_domain.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.domain'`

- [ ] **Step 3: `domain/exception/api_key_error.py` 구현**

```python
"""ApiKey error catalog.

One enum line per error. No class per error (skills/gardevoir-be).
"""

from shared_kernel.exception import ConflictError, ErrorCatalog, ForbiddenError, UnauthorizedError


class ApiKeyError(ErrorCatalog):
    INVALID_KEY = ("APIKEY-001", "the provided API key is not valid", UnauthorizedError)
    GUARDRAIL_NOT_ALLOWED = (
        "APIKEY-002",
        "the requested guardrail is not allowed for this key",
        ForbiddenError,
    )
    NO_GUARDRAIL_CONFIGURED = (
        "APIKEY-003",
        "this key has no guardrail configured",
        ForbiddenError,
    )
    DUPLICATE_NAME = ("APIKEY-004", "an API key with this name already exists", ConflictError)
```

`domain/exception/__init__.py`:

```python
from gateway.domain.exception.api_key_error import ApiKeyError

__all__ = ["ApiKeyError"]
```

- [ ] **Step 4: `domain/models/api_key.py` 구현**

```python
"""ApiKey aggregate.

Persistence-ignorant: no SQLAlchemy, no FastAPI, no httpx.

Guardrail resolution lives here because "a request can never escape the key's
allowed set" is a business rule, independent of how the key is stored or how the
request arrived (§5, §7.2). Putting it in a router or a repository would
duplicate it.
"""

import hashlib
import secrets
from dataclasses import dataclass

from gateway.domain.exception.api_key_error import ApiKeyError

KEY_PREFIX = "gdv_live_"

_TOKEN_BYTES = 32


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_key(raw: str) -> str:
    """Hash a key for storage and cache lookup.

    An API key is high-entropy random, so a fast hash is the right choice.
    bcrypt/argon2 exist for low-entropy human passwords and would be far too
    slow on a path that runs for every request.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: str
    name: str
    key_hash: str
    upstream_base_url: str
    upstream_api_key: str
    allowed_guardrails: tuple[str, ...]
    default_guardrail: str | None
    disabled: bool = False

    def resolve_guardrail(self, requested: str | None) -> str:
        """Resolve the effective guardrail, never escaping the allowed set."""
        if requested:
            if requested not in self.allowed_guardrails:
                ApiKeyError.GUARDRAIL_NOT_ALLOWED.raise_(
                    details={
                        "requested": requested,
                        "allowed": list(self.allowed_guardrails),
                    }
                )
            return requested
        if self.default_guardrail:
            return self.default_guardrail
        if self.allowed_guardrails:
            return self.allowed_guardrails[0]
        ApiKeyError.NO_GUARDRAIL_CONFIGURED.raise_(details={"key_id": self.id})
```

`domain/models/__init__.py`:

```python
from gateway.domain.models.api_key import (
    KEY_PREFIX,
    ApiKey,
    generate_key,
    hash_key,
    parse_bearer,
)

__all__ = ["KEY_PREFIX", "ApiKey", "generate_key", "hash_key", "parse_bearer"]
```

`domain/__init__.py`: 빈 파일.

- [ ] **Step 5: 테스트 통과 확인**

```bash
cd backend/gateway && uv run pytest tests/test_api_key_domain.py -q && uv run ruff check && uv run ruff format --check
```

Expected: 12 passed

- [ ] **Step 6: 돌연변이로 커버리지 확인**

커밋 **전에** 하지 말 것 — `git checkout --`가 커밋하지 않은 수정을 되돌린다.
먼저 커밋한 뒤 Step 8에서 돌린다.

- [ ] **Step 7: 커밋**

```bash
git add backend/gateway
git commit -m "feat: ApiKey 도메인 모델과 에러 카탈로그

가드레일 해석을 도메인에 둔다 — '요청이 키의 허용 집합을 벗어날 수 없다'는
비즈니스 규칙이고 저장소나 전송과 무관하다. 라우터나 리포지토리에 두면
같은 규칙이 여러 곳에 복제된다.

키는 고엔트로피 난수이므로 sha256으로 해시한다. bcrypt/argon2는 저엔트로피
사람 비밀번호를 위한 것이고 요청마다 도는 경로에서는 너무 느리다."
```

- [ ] **Step 8: 돌연변이 검증**

```bash
cd backend/gateway
# 허용 집합 검사를 제거하면 테스트가 잡아야 한다
python3 - <<'PY'
p = "src/gateway/domain/models/api_key.py"
s = open(p).read()
old = "            if requested not in self.allowed_guardrails:"
assert old in s
open(p, "w").write(s.replace(old, "            if False:"))
PY
uv run pytest -q 2>&1 | tail -2   # 반드시 failed 가 나와야 한다
git checkout -- src/
```

Expected: 검사 제거 시 `test_resolve_guardrail_rejects_unallowed` 실패.
통과해버리면 테스트가 규칙을 잡지 못하는 것이므로 테스트를 고친다.

---

## Task 4: 리포지토리 Protocol + ORM + Alembic

**Files:**
- Create: `backend/gateway/src/gateway/application/__init__.py`
- Create: `backend/gateway/src/gateway/application/repository/__init__.py`
- Create: `backend/gateway/src/gateway/application/repository/api_key_repository.py`
- Create: `backend/gateway/src/gateway/infrastructure/__init__.py`
- Create: `backend/gateway/src/gateway/infrastructure/engine.py`
- Create: `backend/gateway/src/gateway/infrastructure/models/__init__.py`
- Create: `backend/gateway/src/gateway/infrastructure/models/api_key.py`
- Create: `backend/gateway/src/gateway/infrastructure/mappers/__init__.py`
- Create: `backend/gateway/src/gateway/infrastructure/mappers/api_key.py`
- Create: `backend/gateway/src/gateway/infrastructure/repository/__init__.py`
- Create: `backend/gateway/src/gateway/infrastructure/repository/api_key_repository.py`
- Create: `backend/gateway/alembic.ini`
- Create: `backend/gateway/alembic/env.py`
- Test: `backend/gateway/tests/test_api_key_repository.py`
- Modify: `backend/gateway/tests/conftest.py`

**Interfaces:**
- Consumes: Task 3의 `ApiKey`, `hash_key`; `shared_kernel.database.{Base, TimestampMixin}`
- Produces:
  - `gateway.application.repository.api_key_repository.ApiKeyRepository` — Protocol:
    `async find_by_hash(key_hash: str) -> ApiKey | None`, `async add(key: ApiKey) -> None`
  - `gateway.infrastructure.engine.get_engine(dsn: str, *, echo: bool = False) -> AsyncEngine`
    (`lru_cache`), `get_session_factory(dsn, *, echo=False)`, `async dispose_engine() -> None`
  - `gateway.infrastructure.models.api_key.ApiKeyModel` — ORM, `__tablename__ = "api_keys"`
  - `gateway.infrastructure.mappers.api_key.to_domain(row) -> ApiKey`,
    `to_model(key: ApiKey) -> ApiKeyModel`
  - `gateway.infrastructure.repository.api_key_repository.SqlAlchemyApiKeyRepository`

**Repository가 쓰기 인터페이스인 이유:** `ApiKey`는 애그리거트이고 도메인 모델로 오간다.
Result DTO를 반환하는 조회는 DAO의 일이지만, Phase 1b에는 조회 화면이 없으므로 DAO를
만들지 않는다 — 관리 API는 Phase 2다 (§5).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/gateway/tests/test_api_key_repository.py`:

```python
import pytest

from gateway.domain.models.api_key import ApiKey, generate_key, hash_key
from gateway.infrastructure.mappers.api_key import to_domain, to_model
from gateway.infrastructure.models.api_key import ApiKeyModel
from gateway.infrastructure.repository.api_key_repository import SqlAlchemyApiKeyRepository


def _key(raw: str, **kw) -> ApiKey:
    fields = dict(
        id="k-repo",
        name="repo-test",
        key_hash=hash_key(raw),
        upstream_base_url="https://api.openai.com/v1",
        upstream_api_key="sk-upstream",
        allowed_guardrails=("base", "doc-agent"),
        default_guardrail="base",
        disabled=False,
    )
    fields.update(kw)
    return ApiKey(**fields)


def test_mapper_roundtrip_preserves_every_field():
    raw = generate_key()
    key = _key(raw)
    restored = to_domain(to_model(key))
    assert restored == key


def test_mapper_returns_guardrails_as_a_tuple():
    """jsonb는 list로 돌아온다. 도메인은 불변이어야 하므로 tuple로 바꿔야 한다."""
    model = ApiKeyModel(
        id="k1",
        name="n",
        key_hash="h",
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=["base"],
        default_guardrail="base",
        disabled=False,
    )
    assert to_domain(model).allowed_guardrails == ("base",)


async def test_add_then_find_by_hash(session):
    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw))
    await session.commit()

    found = await repo.find_by_hash(hash_key(raw))
    assert found is not None
    assert found.id == "k-repo"
    assert found.upstream_api_key == "sk-upstream"
    assert found.allowed_guardrails == ("base", "doc-agent")


async def test_find_by_hash_returns_none_for_unknown(session):
    repo = SqlAlchemyApiKeyRepository(session)
    assert await repo.find_by_hash(hash_key(generate_key())) is None


async def test_disabled_key_is_not_returned(session):
    """비활성 키가 조회되면 키 회수가 무의미해진다."""
    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw, id="k-off", disabled=True))
    await session.commit()

    assert await repo.find_by_hash(hash_key(raw)) is None


async def test_duplicate_hash_is_rejected_by_the_database(session):
    """같은 키가 두 번 등록되면 어느 쪽이 유효한지 알 수 없다."""
    import sqlalchemy.exc

    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw, id="k-a"))
    await session.commit()

    await repo.add(_key(raw, id="k-b", name="other"))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await session.commit()


async def test_raw_key_is_never_stored(session):
    raw = generate_key()
    repo = SqlAlchemyApiKeyRepository(session)
    await repo.add(_key(raw))
    await session.commit()

    row = (await session.execute(__import__("sqlalchemy").select(ApiKeyModel))).scalar_one()
    for value in (row.key_hash, row.name, row.upstream_api_key, row.upstream_base_url):
        assert raw not in value
```

`backend/gateway/tests/conftest.py`에 추가:

```python
import pytest_asyncio
from shared_kernel.database import Base
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.settings import get_settings

# ORM 모델을 임포트해야 Base.metadata 에 등록된다.
import gateway.infrastructure.models  # noqa: F401  isort:skip


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Session-scoped engine with a freshly created schema.

    `docker compose --env-file infra/envs/example/compose.env
     -f infra/docker-compose/postgres.yml up -d` 가 먼저 떠 있어야 한다.
    """
    eng = create_async_engine(get_settings().database.dsn)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    """Per-test session; every table is truncated afterwards."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.exec_driver_sql(f'TRUNCATE TABLE "{table.name}" CASCADE')
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
docker compose --env-file infra/envs/example/compose.env \
  -f infra/docker-compose/postgres.yml up -d
cd backend/gateway && uv run pytest tests/test_api_key_repository.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.infrastructure'`

- [ ] **Step 3: `application/repository/api_key_repository.py` 구현**

```python
"""ApiKey write interface.

Repository operates on the domain aggregate. A read projection that returns a
result DTO would be a Dao — there is no read surface until the admin API in
Phase 2 (§5).
"""

from typing import Protocol

from gateway.domain.models.api_key import ApiKey


class ApiKeyRepository(Protocol):
    async def find_by_hash(self, key_hash: str) -> ApiKey | None: ...

    async def add(self, key: ApiKey) -> None: ...
```

`application/repository/__init__.py`:

```python
from gateway.application.repository.api_key_repository import ApiKeyRepository

__all__ = ["ApiKeyRepository"]
```

`application/__init__.py`: 빈 파일.

- [ ] **Step 4: `infrastructure/models/api_key.py` 구현**

```python
"""ApiKey ORM model."""

from shared_kernel.database import Base, TimestampMixin
from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ApiKeyModel(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    #: sha256 hex of the raw key. The raw key is never stored.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    upstream_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    upstream_api_key: Mapped[str] = mapped_column(String(512), nullable=False)

    #: Guardrails this key may select via X-Gardevoir-Guardrail. A request can
    #: never escape this set — that is why guardrail choice is bound to the
    #: credential rather than to a header (§7.2).
    allowed_guardrails: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    default_guardrail: Mapped[str | None] = mapped_column(String(255), nullable=True)

    disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
```

`infrastructure/models/__init__.py` — **모든 모델을 re-export**해야 `Base.metadata`에
등록된다. 빠뜨리면 Alembic autogenerate가 테이블을 놓친다:

```python
from gateway.infrastructure.models.api_key import ApiKeyModel

__all__ = ["ApiKeyModel"]
```

- [ ] **Step 5: `infrastructure/mappers/api_key.py` 구현**

```python
"""ApiKey domain <-> ORM mapping."""

from gateway.domain.models.api_key import ApiKey
from gateway.infrastructure.models.api_key import ApiKeyModel


def to_domain(row: ApiKeyModel) -> ApiKey:
    return ApiKey(
        id=row.id,
        name=row.name,
        key_hash=row.key_hash,
        upstream_base_url=row.upstream_base_url,
        upstream_api_key=row.upstream_api_key,
        # jsonb comes back as a list; the aggregate is immutable.
        allowed_guardrails=tuple(row.allowed_guardrails or ()),
        default_guardrail=row.default_guardrail,
        disabled=row.disabled,
    )


def to_model(key: ApiKey) -> ApiKeyModel:
    return ApiKeyModel(
        id=key.id,
        name=key.name,
        key_hash=key.key_hash,
        upstream_base_url=key.upstream_base_url,
        upstream_api_key=key.upstream_api_key,
        allowed_guardrails=list(key.allowed_guardrails),
        default_guardrail=key.default_guardrail,
        disabled=key.disabled,
    )
```

`infrastructure/mappers/__init__.py`:

```python
from gateway.infrastructure.mappers.api_key import to_domain, to_model

__all__ = ["to_domain", "to_model"]
```

- [ ] **Step 6: `infrastructure/repository/api_key_repository.py` 구현**

```python
"""SQLAlchemy ApiKey repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.domain.models.api_key import ApiKey
from gateway.infrastructure.mappers.api_key import to_domain, to_model
from gateway.infrastructure.models.api_key import ApiKeyModel


class SqlAlchemyApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        row = (
            await self._session.execute(
                select(ApiKeyModel).where(
                    ApiKeyModel.key_hash == key_hash,
                    ApiKeyModel.disabled.is_(False),
                )
            )
        ).scalar_one_or_none()
        return to_domain(row) if row is not None else None

    async def add(self, key: ApiKey) -> None:
        self._session.add(to_model(key))
        await self._session.flush()
```

`infrastructure/repository/__init__.py`:

```python
from gateway.infrastructure.repository.api_key_repository import SqlAlchemyApiKeyRepository

__all__ = ["SqlAlchemyApiKeyRepository"]
```

- [ ] **Step 7: `infrastructure/engine.py` 구현**

```python
"""Lazy engine and session factory.

Cached so repeated composition calls reuse one pool, and disposed in the app
lifespan.
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@lru_cache
def get_engine(dsn: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(dsn, echo=echo, pool_pre_ping=True)


@lru_cache
def get_session_factory(dsn: str, *, echo: bool = False) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(dsn, echo=echo), expire_on_commit=False)


async def dispose_engine() -> None:
    for engine in list(get_engine.cache_parameters() and get_engine.cache_info() and []):
        pass  # placeholder replaced below
```

> `dispose_engine`은 `lru_cache`에서 인스턴스를 직접 꺼낼 수 없으므로 아래 형태로 쓴다:

```python
_engines: list[AsyncEngine] = []


@lru_cache
def get_engine(dsn: str, *, echo: bool = False) -> AsyncEngine:
    engine = create_async_engine(dsn, echo=echo, pool_pre_ping=True)
    _engines.append(engine)
    return engine


async def dispose_engine() -> None:
    while _engines:
        await _engines.pop().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
```

최종 파일은 `_engines` 리스트를 쓰는 형태 하나만 담는다 — 위의 placeholder 버전은
쓰지 않는다.

`infrastructure/__init__.py`: 빈 파일.

- [ ] **Step 8: Alembic 초기화**

```bash
cd backend/gateway && uv run alembic init -t async alembic
```

`alembic.ini`에서 `sqlalchemy.url` 줄을 **삭제**한다 (설정에서 읽는다).

`alembic/env.py`의 임포트 아래에 추가하고 `target_metadata = None`을 교체한다:

```python
from shared_kernel.database import Base

import gateway.infrastructure.models  # noqa: F401  metadata 등록
from gateway.settings import get_settings

config.set_main_option("sqlalchemy.url", get_settings().database.dsn)
target_metadata = Base.metadata
```

마이그레이션 생성:

```bash
docker compose --env-file infra/envs/example/compose.env \
  -f infra/docker-compose/postgres.yml up -d
cd backend/gateway && uv run alembic revision --autogenerate -m "api_keys 테이블"
uv run alembic upgrade head
```

확인:

```bash
docker exec gardevoir-postgres-1 psql -U gardevoir -c '\d api_keys'
```

Expected: `pk_api_keys`, `uq_api_keys_key_hash`(또는 `ix_api_keys_key_hash`) 이름이
`shared_kernel`의 naming_convention을 따른다.

- [ ] **Step 9: 테스트 통과 확인**

```bash
cd backend/gateway && uv run pytest -q && uv run ruff check && uv run ruff format --check
```

Expected: 모두 통과

- [ ] **Step 10: 커밋**

```bash
git add backend/gateway
git commit -m "feat: ApiKey 리포지토리와 Alembic 마이그레이션

Repository는 도메인 애그리거트를 다루는 쓰기 인터페이스다. Result DTO를
반환하는 조회는 DAO의 일이지만 Phase 1b에는 조회 화면이 없어 만들지 않는다.

비활성 키는 조회되지 않는다 — 그러지 않으면 키 회수가 무의미해진다.
key_hash에 unique를 걸어 같은 키의 중복 등록을 DB가 막는다."
```

---

## Task 5: 캐시 리포지토리 — 핫패스에서 DB 제거

§6은 요청 경로에 DB 접근이 없을 것을 요구한다. 키 조회가 유일한 DB 접근이므로 여기서
덮는다. **리포지토리 Protocol을 그대로 구현하는 데코레이터**로 만들어, 서비스가
캐시의 존재를 모르게 한다 — 레이어링은 의존 방향을 규정하고 캐싱은 구현 자유다.

**Files:**
- Create: `backend/gateway/src/gateway/infrastructure/repository/cached_api_key_repository.py`
- Modify: `backend/gateway/src/gateway/infrastructure/repository/__init__.py`
- Test: `backend/gateway/tests/test_cached_api_key_repository.py`

**Interfaces:**
- Consumes: Task 4의 `ApiKeyRepository` Protocol, `ApiKey`
- Produces:
  - `CachedApiKeyRepository` — `__init__(inner: ApiKeyRepository, *, ttl_s: float, clock: Callable[[], float] = time.monotonic)`,
    `async find_by_hash(...)`, `async add(...)`, `invalidate(key_hash: str)`, `clear()`,
    `hits: int`, `misses: int`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/gateway/tests/test_cached_api_key_repository.py`:

```python
from gateway.domain.models.api_key import ApiKey, generate_key, hash_key
from gateway.infrastructure.repository.cached_api_key_repository import CachedApiKeyRepository


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class CountingRepository:
    """Records how often the slow path was taken."""

    def __init__(self, keys: dict[str, ApiKey] | None = None) -> None:
        self.keys = keys or {}
        self.lookups = 0
        self.added: list[ApiKey] = []

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        self.lookups += 1
        return self.keys.get(key_hash)

    async def add(self, key: ApiKey) -> None:
        self.added.append(key)
        self.keys[key.key_hash] = key


def _key(raw: str) -> ApiKey:
    return ApiKey(
        id="k1",
        name="app",
        key_hash=hash_key(raw),
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=("base",),
        default_guardrail="base",
    )


async def test_second_lookup_does_not_touch_the_inner_repository():
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    assert (await cache.find_by_hash(hash_key(raw))).id == "k1"
    assert (await cache.find_by_hash(hash_key(raw))).id == "k1"
    assert inner.lookups == 1
    assert cache.hits == 1
    assert cache.misses == 1


async def test_entry_expires_after_ttl():
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    clock = FakeClock()
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=clock)

    await cache.find_by_hash(hash_key(raw))
    clock.advance(31.0)
    await cache.find_by_hash(hash_key(raw))
    assert inner.lookups == 2


async def test_unknown_key_is_negative_cached():
    """무효한 키를 반복 전송하는 것만으로 DB에 부하를 줄 수 있어서는 안 된다."""
    inner = CountingRepository()
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())
    h = hash_key(generate_key())

    assert await cache.find_by_hash(h) is None
    assert await cache.find_by_hash(h) is None
    assert inner.lookups == 1
    assert cache.hits == 1


async def test_invalidate_forces_reload():
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    await cache.find_by_hash(hash_key(raw))
    cache.invalidate(hash_key(raw))
    await cache.find_by_hash(hash_key(raw))
    assert inner.lookups == 2


async def test_add_invalidates_so_the_new_key_is_visible():
    """등록 직후 조회가 부정 캐시에 막히면 새 키가 TTL 동안 죽는다."""
    raw = generate_key()
    inner = CountingRepository()
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())

    assert await cache.find_by_hash(hash_key(raw)) is None  # 부정 캐시 적재
    await cache.add(_key(raw))
    found = await cache.find_by_hash(hash_key(raw))
    assert found is not None
    assert found.id == "k1"


async def test_cache_is_keyed_by_hash_not_raw_key():
    """캐시 구조에 원본 크레덴셜이 남으면 메모리 덤프로 유출된다."""
    raw = generate_key()
    inner = CountingRepository({hash_key(raw): _key(raw)})
    cache = CachedApiKeyRepository(inner, ttl_s=30.0, clock=FakeClock())
    await cache.find_by_hash(hash_key(raw))

    assert all(raw not in k for k in cache._entries)
    assert hash_key(raw) in cache._entries
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/gateway && uv run pytest tests/test_cached_api_key_repository.py -q
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: `cached_api_key_repository.py` 구현**

```python
"""In-memory caching decorator over an ApiKeyRepository.

설계 문서 §6은 요청 경로에 DB 접근이 없을 것을 요구한다. 키 조회가 유일한 DB
접근이므로 여기서 덮는다. 존재하지 않는 키도 캐싱한다 — 그러지 않으면 무효한
키를 반복 전송하는 것만으로 DB에 부하를 줄 수 있다.

레이어링은 의존 방향을 규정하고 캐싱은 구현 자유다. 이 클래스가 리포지토리
Protocol을 그대로 구현하므로 서비스는 캐시의 존재를 모른다.
"""

import time
from collections.abc import Callable

from gateway.application.repository.api_key_repository import ApiKeyRepository
from gateway.domain.models.api_key import ApiKey


class CachedApiKeyRepository:
    def __init__(
        self,
        inner: ApiKeyRepository,
        *,
        ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl_s = ttl_s
        self._clock = clock
        #: key_hash -> (expires_at, value). The raw key never appears here.
        self._entries: dict[str, tuple[float, ApiKey | None]] = {}
        self.hits = 0
        self.misses = 0

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        now = self._clock()
        entry = self._entries.get(key_hash)
        if entry is not None and entry[0] > now:
            self.hits += 1
            return entry[1]

        self.misses += 1
        value = await self._inner.find_by_hash(key_hash)
        self._entries[key_hash] = (now + self._ttl_s, value)
        return value

    async def add(self, key: ApiKey) -> None:
        await self._inner.add(key)
        # 부정 캐시가 남아 있으면 새 키가 TTL 동안 죽는다.
        self.invalidate(key.key_hash)

    def invalidate(self, key_hash: str) -> None:
        self._entries.pop(key_hash, None)

    def clear(self) -> None:
        self._entries.clear()
```

`infrastructure/repository/__init__.py`를 교체:

```python
from gateway.infrastructure.repository.api_key_repository import SqlAlchemyApiKeyRepository
from gateway.infrastructure.repository.cached_api_key_repository import CachedApiKeyRepository

__all__ = ["CachedApiKeyRepository", "SqlAlchemyApiKeyRepository"]
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd backend/gateway && uv run pytest tests/test_cached_api_key_repository.py -q && uv run ruff check && uv run ruff format --check
```

Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/gateway
git commit -m "feat: TTL 키 캐시로 핫패스에서 DB 제거

리포지토리 Protocol을 그대로 구현하는 데코레이터로 만들어 서비스가 캐시의
존재를 모르게 한다. 레이어링은 의존 방향을 규정하고 캐싱은 구현 자유다.

캐시 키는 sha256 해시다 — 메모리 덤프에 원본 크레덴셜이 남지 않게 한다.
존재하지 않는 키도 캐싱해 무효 키 반복 전송으로 DB에 부하를 주는 것을 막는다.
add는 부정 캐시를 무효화한다 — 그러지 않으면 새 키가 TTL 동안 죽는다."
```

---

## Task 6: 인증 서비스 + 앱 조립 + `/healthz`

**Files:**
- Create: `backend/gateway/src/gateway/application/service/__init__.py`
- Create: `backend/gateway/src/gateway/application/service/authentication_service.py`
- Create: `backend/gateway/src/gateway/composition.py`
- Create: `backend/gateway/src/gateway/presentation/__init__.py`
- Create: `backend/gateway/src/gateway/presentation/http/__init__.py`
- Create: `backend/gateway/src/gateway/presentation/http/app.py`
- Create: `backend/gateway/src/gateway/presentation/http/health.py`
- Test: `backend/gateway/tests/test_authentication_service.py`
- Test: `backend/gateway/tests/test_app.py`

**Interfaces:**
- Consumes: 앞선 모든 태스크
- Produces:
  - `gateway.application.service.authentication_service.AuthenticatedRequest` —
    frozen dataclass: `key: ApiKey`, `guardrail: str`, `mode: Mode`
  - `gateway.application.service.authentication_service.AuthenticationService` —
    `__init__(*, keys: ApiKeyRepository)`,
    `async authenticate(*, authorization: str | None, guardrail: str | None, mode: str | None) -> AuthenticatedRequest`
  - `gateway.composition.provide_authentication_service(...)` — FastAPI `Depends`
  - `gateway.presentation.http.app.create_app(settings=None) -> FastAPI`
  - `app.state.key_cache: CachedApiKeyRepository`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/gateway/tests/test_authentication_service.py`:

```python
import pytest
from shared_kernel.exception import ForbiddenError, UnauthorizedError

from gateway.application.service.authentication_service import AuthenticationService
from gateway.contract import Mode
from gateway.domain.models.api_key import ApiKey, generate_key, hash_key


class StubRepository:
    def __init__(self, keys: dict[str, ApiKey] | None = None) -> None:
        self.keys = keys or {}

    async def find_by_hash(self, key_hash: str) -> ApiKey | None:
        return self.keys.get(key_hash)

    async def add(self, key: ApiKey) -> None:
        self.keys[key.key_hash] = key


def _service(raw: str | None = None, **kw) -> AuthenticationService:
    keys = {}
    if raw is not None:
        fields = dict(
            id="k1",
            name="app",
            key_hash=hash_key(raw),
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="sk-upstream",
            allowed_guardrails=("base", "doc-agent"),
            default_guardrail="base",
        )
        fields.update(kw)
        keys[hash_key(raw)] = ApiKey(**fields)
    return AuthenticationService(keys=StubRepository(keys))


async def test_authenticates_and_resolves_defaults():
    raw = generate_key()
    result = await _service(raw).authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode=None
    )
    assert result.key.id == "k1"
    assert result.guardrail == "base"
    assert result.mode is Mode.ENFORCE


async def test_missing_authorization_is_401():
    with pytest.raises(UnauthorizedError) as info:
        await _service().authenticate(authorization=None, guardrail=None, mode=None)
    assert info.value.code == "APIKEY-001"


async def test_malformed_authorization_is_401():
    with pytest.raises(UnauthorizedError):
        await _service().authenticate(authorization="Basic abc", guardrail=None, mode=None)


async def test_unknown_key_is_401():
    with pytest.raises(UnauthorizedError) as info:
        await _service().authenticate(
            authorization=f"Bearer {generate_key()}", guardrail=None, mode=None
        )
    assert info.value.code == "APIKEY-001"


async def test_unallowed_guardrail_is_403():
    raw = generate_key()
    with pytest.raises(ForbiddenError) as info:
        await _service(raw).authenticate(
            authorization=f"Bearer {raw}", guardrail="internal-analytics", mode=None
        )
    assert info.value.code == "APIKEY-002"


async def test_dry_run_is_accepted_without_a_permission_check():
    """모드는 자유 선택이다 — 공격자는 헤더를 만지지 못하고 대화 텍스트만 통제한다."""
    raw = generate_key()
    result = await _service(raw).authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode="dry-run"
    )
    assert result.mode is Mode.DRY_RUN


async def test_unknown_mode_falls_back_to_enforce():
    raw = generate_key()
    result = await _service(raw).authenticate(
        authorization=f"Bearer {raw}", guardrail=None, mode="off"
    )
    assert result.mode is Mode.ENFORCE
```

`backend/gateway/tests/test_app.py`:

```python
import httpx
import pytest_asyncio
from shared_kernel.log import REQUEST_ID_HEADER

from gateway.domain.models.api_key import generate_key
from gateway.presentation.http.app import create_app


@pytest_asyncio.fixture
async def app(engine):
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_request_id_is_echoed(client):
    r = await client.get("/healthz", headers={REQUEST_ID_HEADER: "req_caller"})
    assert r.headers[REQUEST_ID_HEADER] == "req_caller"


async def test_request_id_is_generated_when_absent(client):
    r = await client.get("/healthz")
    assert r.headers[REQUEST_ID_HEADER]


async def test_unknown_route_is_json_shaped(client):
    """404가 shared_kernel의 ErrorResponse 형태로 나가야 한다.

    FastAPI 기본 404는 {"detail": ...} 이므로, 중앙 핸들러가 HTTPException을
    받지 않으면 여기서 드러난다.
    """
    r = await client.get("/nope")
    assert r.status_code == 404
    body = r.json()
    assert "code" in body
    assert "message" in body
    assert "detail" not in body


async def test_unhandled_error_response_carries_request_id(client, app):
    """미처리 예외 500에도 상관 ID가 붙어야 한다.

    Exception 핸들러는 RequestContextMiddleware 바깥의 ServerErrorMiddleware에서
    돌기 때문에 순진하게 조립하면 헤더가 빠진다.
    """

    @app.get("/boom-test")
    async def boom():
        raise RuntimeError("kaboom")

    r = await client.get("/boom-test")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL"
    assert "kaboom" not in r.text
    assert r.headers.get(REQUEST_ID_HEADER)


async def test_key_cache_is_wired_into_app_state(app):
    assert app.state.key_cache is not None
    assert app.state.key_cache.misses == 0
```

> `test_unknown_route_is_json_shaped`와 `test_unhandled_error_response_carries_request_id`는
> Phase 1a 검토가 Phase 1b로 넘긴 두 항목(B-1, B-2)이다. 여기서 처음으로 앱을
> 조립하므로 이제 관측 가능하다.

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/gateway && uv run pytest tests/test_authentication_service.py tests/test_app.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.application.service'`

- [ ] **Step 3: `authentication_service.py` 구현**

```python
"""Authentication use case.

키 조회와 가드레일 해석을 한 유스케이스로 묶는다. 라우터는 이 서비스 하나에만
의존한다.
"""

from dataclasses import dataclass

from gateway.application.repository.api_key_repository import ApiKeyRepository
from gateway.contract import Mode
from gateway.domain.exception.api_key_error import ApiKeyError
from gateway.domain.models.api_key import ApiKey, hash_key, parse_bearer


@dataclass(frozen=True, slots=True)
class AuthenticatedRequest:
    key: ApiKey
    guardrail: str
    mode: Mode


class AuthenticationService:
    def __init__(self, *, keys: ApiKeyRepository) -> None:
        self._keys = keys

    async def authenticate(
        self,
        *,
        authorization: str | None,
        guardrail: str | None,
        mode: str | None,
    ) -> AuthenticatedRequest:
        raw = parse_bearer(authorization)
        if raw is None:
            ApiKeyError.INVALID_KEY.raise_()

        key = await self._keys.find_by_hash(hash_key(raw))
        if key is None:
            ApiKeyError.INVALID_KEY.raise_()

        return AuthenticatedRequest(
            key=key,
            guardrail=key.resolve_guardrail(guardrail),
            # 모드는 권한 검사 없이 자유 선택이다. 공격자는 대화 텍스트만 통제하고
            # HTTP 헤더는 만지지 못하므로 dry-run이 자유여도 도움이 되지 않는다.
            # 남는 리스크는 거버넌스이고, 그것은 감사 로그에 모드를 남겨 드러낸다.
            mode=Mode.parse(mode),
        )
```

`application/service/__init__.py`:

```python
from gateway.application.service.authentication_service import (
    AuthenticatedRequest,
    AuthenticationService,
)

__all__ = ["AuthenticatedRequest", "AuthenticationService"]
```

- [ ] **Step 4: `composition.py` 구현**

```python
"""Composition root.

인프라 구현체와 fastapi.Depends를 임포트하는 유일한 곳이다. presentation은
여기서 서비스만 가져간다 (skills/gardevoir-be).
"""

from typing import Annotated

from fastapi import Depends, Request

from gateway.application.service.authentication_service import AuthenticationService


def provide_authentication_service(request: Request) -> AuthenticationService:
    # 캐시 리포지토리는 프로세스 수명 동안 유지되어야 하므로 app.state 가 소유한다.
    return AuthenticationService(keys=request.app.state.key_cache)


AuthenticationServiceDep = Annotated[
    AuthenticationService, Depends(provide_authentication_service)
]
```

- [ ] **Step 5: `presentation/http/health.py`와 `app.py` 구현**

`health.py`:

```python
"""Liveness endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

`app.py`:

```python
"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from shared_kernel.exception import ValidationError as AppValidationError
from shared_kernel.exception import register_exception_handlers
from shared_kernel.log import RequestContextMiddleware, configure_logging

from gateway.infrastructure.engine import dispose_engine, get_session_factory
from gateway.infrastructure.repository import (
    CachedApiKeyRepository,
    SqlAlchemyApiKeyRepository,
)
from gateway.presentation.http import health
from gateway.settings import GatewaySettings, get_settings

logger = logging.getLogger(__name__)


class _SessionScopedApiKeyRepository:
    """Opens a short-lived session per lookup.

    캐시가 앞에 있어 대부분의 요청은 여기까지 오지 않는다 (§6).
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def find_by_hash(self, key_hash: str):
        async with self._session_factory() as session:
            return await SqlAlchemyApiKeyRepository(session).find_by_hash(key_hash)

    async def add(self, key) -> None:
        async with self._session_factory() as session:
            await SqlAlchemyApiKeyRepository(session).add(key)
            await session.commit()


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        factory = get_session_factory(settings.database.dsn, echo=settings.database.echo)
        app.state.key_cache = CachedApiKeyRepository(
            _SessionScopedApiKeyRepository(factory), ttl_s=settings.key_cache_ttl_s
        )
        try:
            yield
        finally:
            await dispose_engine()

    app = FastAPI(title="gardevoir gateway", version="0.1.0", lifespan=lifespan)

    # 미들웨어를 먼저 등록해 상관 ID가 핸들러보다 바깥에 있게 한다.
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    # FastAPI가 자체 처리하는 두 예외도 같은 응답 형태로 끌어온다.
    # 그러지 않으면 404/422가 {"detail": ...} 로 새어나가 계약이 둘이 된다.
    @app.exception_handler(HTTPException)
    async def _http_exception(request: Request, exc: HTTPException) -> Response:
        from shared_kernel.exception.base import AppError

        mapped = AppError(exc.detail if isinstance(exc.detail, str) else "request failed")
        mapped.http_status = exc.status_code
        mapped.code = f"HTTP-{exc.status_code}"
        mapped.log_level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        return await app.exception_handlers[AppError](request, mapped)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        from shared_kernel.exception.base import AppError

        # errors()의 input/url은 호출자 페이로드와 내부 경로를 담으므로 싣지 않는다.
        safe = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()
        ]
        mapped = AppValidationError("request validation failed", details={"errors": safe})
        return await app.exception_handlers[AppError](request, mapped)

    app.include_router(health.router)
    return app
```

> **주의:** 위 두 핸들러는 `app.exception_handlers[AppError]`를 재사용한다. FastAPI가
> 등록한 핸들러를 그렇게 꺼낼 수 없으면 `shared_kernel.exception.handlers`에서 응답
> 조립 함수를 직접 임포트하는 형태로 바꾼다. 어느 쪽이든 **응답 형태가 하나여야 한다는
> 것이 요구사항이고**, `test_unknown_route_is_json_shaped`가 그것을 고정한다.

`presentation/http/__init__.py`, `presentation/__init__.py`: 빈 파일.

- [ ] **Step 6: 테스트 통과 확인**

```bash
docker compose --env-file infra/envs/example/compose.env \
  -f infra/docker-compose/postgres.yml up -d
cd backend/gateway && uv run pytest -q && uv run ruff check && uv run ruff format --check
```

Expected: 모두 통과.

`test_unhandled_error_response_carries_request_id`가 실패하면 미들웨어와 핸들러의
순서 문제다. `ServerErrorMiddleware`가 `RequestContextMiddleware`보다 바깥에 있어
`Exception` 핸들러의 응답에 헤더가 붙지 않는다. 해결: `Exception` 핸들러 안에서
`shared_kernel.log.get_request_id()`를 읽어 응답 헤더에 직접 넣는다. 그 수정은
`shared_kernel`의 핸들러에 하고, Phase 1a 테스트도 함께 갱신한다.

- [ ] **Step 7: 실제 기동 확인**

```bash
cd backend/gateway
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn --factory gateway.presentation.http.app:create_app --port 21000 &
sleep 2
curl -si localhost:21000/healthz | head -6
curl -si localhost:21000/nope | head -8
kill %1
rm .env
```

Expected: `/healthz`는 `{"status":"ok"}` + `X-Request-Id` 헤더.
`/nope`는 404 + `{"code": ..., "message": ...}` (`{"detail": ...}` 가 아님).

- [ ] **Step 8: 커밋**

```bash
git add backend/gateway
git commit -m "feat: 인증 서비스와 앱 조립

라우터는 AuthenticationService 하나에만 의존한다. composition.py가 인프라
구현체와 Depends를 임포트하는 유일한 곳이다.

모드는 권한 검사 없이 자유 선택이다 — 공격자는 대화 텍스트만 통제하고 HTTP
헤더는 만지지 못하므로 dry-run이 자유여도 도움이 되지 않는다. 남는 리스크는
거버넌스이고 감사 로그에 모드를 남겨 드러낸다.

Phase 1a 검토가 넘긴 두 항목을 여기서 처리한다: HTTPException과
RequestValidationError를 중앙 응답 형태로 끌어오고, 미처리 예외 500에도
상관 ID가 붙는지 테스트로 고정한다."
```

---

## Task 7: 키 발급 CLI

운영자가 키를 만들 수단이 없으면 Phase 1c의 E2E 테스트도 손으로 SQL을 써야 한다.

**Files:**
- Create: `backend/gateway/src/gateway/cli.py`
- Modify: `backend/gateway/pyproject.toml` (`[project.scripts]`)
- Test: `backend/gateway/tests/test_cli.py`

**Interfaces:**
- Consumes: Task 3~4
- Produces:
  - `gateway.cli.create_key(*, name, upstream_base_url, upstream_api_key, allowed_guardrails, default_guardrail) -> str`
    — 원본 키를 반환한다(저장하지 않으므로 이때만 볼 수 있다)
  - 콘솔 스크립트 `gardevoir-createkey`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/gateway/tests/test_cli.py`:

```python
from sqlalchemy import select

from gateway.cli import create_key
from gateway.domain.models.api_key import KEY_PREFIX, hash_key
from gateway.infrastructure.models.api_key import ApiKeyModel


async def test_create_key_persists_only_the_hash(engine, session):
    raw = await create_key(
        session_factory=lambda: session,
        name="e2e",
        upstream_base_url="https://api.openai.com/v1",
        upstream_api_key="sk-upstream",
        allowed_guardrails=["base"],
        default_guardrail="base",
    )
    await session.commit()

    assert raw.startswith(KEY_PREFIX)
    row = (await session.execute(select(ApiKeyModel))).scalar_one()
    assert row.key_hash == hash_key(raw)
    assert raw not in row.key_hash
    assert row.allowed_guardrails == ["base"]


async def test_created_key_authenticates(engine, session):
    from gateway.application.service.authentication_service import AuthenticationService
    from gateway.infrastructure.repository import SqlAlchemyApiKeyRepository

    raw = await create_key(
        session_factory=lambda: session,
        name="e2e2",
        upstream_base_url="u",
        upstream_api_key="s",
        allowed_guardrails=["base", "doc-agent"],
        default_guardrail="base",
    )
    await session.commit()

    service = AuthenticationService(keys=SqlAlchemyApiKeyRepository(session))
    result = await service.authenticate(
        authorization=f"Bearer {raw}", guardrail="doc-agent", mode=None
    )
    assert result.guardrail == "doc-agent"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/gateway && uv run pytest tests/test_cli.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.cli'`

- [ ] **Step 3: `cli.py` 구현**

```python
"""Operator entry points."""

import argparse
import asyncio
from collections.abc import Callable

from ulid import ULID

from gateway.domain.models.api_key import ApiKey, generate_key, hash_key
from gateway.infrastructure.engine import dispose_engine, get_session_factory
from gateway.infrastructure.repository import SqlAlchemyApiKeyRepository
from gateway.settings import get_settings


async def create_key(
    *,
    session_factory: Callable,
    name: str,
    upstream_base_url: str,
    upstream_api_key: str,
    allowed_guardrails: list[str],
    default_guardrail: str | None,
) -> str:
    """Create a key and return the raw value.

    Only the hash is stored, so this return value is the only time the key is
    visible.
    """
    raw = generate_key()
    key = ApiKey(
        id=str(ULID()),
        name=name,
        key_hash=hash_key(raw),
        upstream_base_url=upstream_base_url,
        upstream_api_key=upstream_api_key,
        allowed_guardrails=tuple(allowed_guardrails),
        default_guardrail=default_guardrail,
    )
    session = session_factory()
    await SqlAlchemyApiKeyRepository(session).add(key)
    return raw


def createkey() -> None:
    parser = argparse.ArgumentParser(description="Create a gardevoir API key")
    parser.add_argument("--name", required=True)
    parser.add_argument("--upstream-base-url", default="https://api.openai.com/v1")
    parser.add_argument("--upstream-api-key", required=True)
    parser.add_argument("--guardrail", action="append", default=None)
    args = parser.parse_args()

    guardrails = args.guardrail or ["base"]
    print(asyncio.run(_run(args, guardrails)))


async def _run(args, guardrails: list[str]) -> str:
    settings = get_settings()
    factory = get_session_factory(settings.database.dsn)
    async with factory() as session:
        raw = await create_key(
            session_factory=lambda: session,
            name=args.name,
            upstream_base_url=args.upstream_base_url,
            upstream_api_key=args.upstream_api_key,
            allowed_guardrails=guardrails,
            default_guardrail=guardrails[0],
        )
        await session.commit()
    await dispose_engine()
    return raw
```

`pyproject.toml`에 추가:

```toml
[project.scripts]
gardevoir-createkey = "gateway.cli:createkey"
```

- [ ] **Step 4: 테스트 통과 확인 + 실제 실행**

```bash
cd backend/gateway && uv run pytest -q && uv run ruff check && uv run ruff format --check
cp .env.example .env
uv run alembic upgrade head
uv run gardevoir-createkey --name local-dev --upstream-api-key sk-dummy --guardrail base
rm .env
```

Expected: `gdv_live_...` 한 줄 출력. 같은 명령을 두 번 돌리면 서로 다른 키가 나온다.

- [ ] **Step 5: 커밋**

```bash
git add backend/gateway
git commit -m "feat: 키 발급 CLI

원본 키는 저장하지 않으므로 발급 시 출력이 유일하게 볼 수 있는 시점이다.
Phase 1c의 E2E 테스트가 손으로 SQL을 쓰지 않게 한다."
```

---

## Self-Review

**1. Spec coverage (Phase 1b 범위)**

| 요구사항 | 태스크 |
|---|---|
| gateway 워크스페이스 멤버 + 설정 | Task 1 |
| 와이어 계약 (§7.2, §7.3) | Task 2 |
| SDK 확장 필드 회귀 테스트 (§11.9) | Task 2 |
| 계약 버전은 URL이 담당 (헤더 없음) | Task 2 |
| ApiKey 애그리거트 + 가드레일 해석 (§7.2) | Task 3 |
| ErrorCatalog (클래스당 에러 금지) | Task 3 |
| Repository Protocol + ORM + mapper | Task 4 |
| Alembic + naming_convention | Task 4 |
| 핫패스에서 DB 제거 (§6) | Task 5 |
| 인증 유스케이스 + composition 루트 | Task 6 |
| dry-run 자유 선택 (§7.2) | Task 6 |
| `HTTPException`/`RequestValidationError` 흡수 (1a 검토 B-1) | Task 6 |
| 미처리 예외 500의 `X-Request-Id` (1a 검토 B-2) | Task 6 |
| 키 발급 수단 | Task 7 |

**Phase 1b 범위 밖 (Phase 1c):** `/v1/chat/completions` 라우트, httpx 업스트림 중계
(비스트리밍 + SSE), ClickHouse 감사 sink, `base_url` 교체 E2E.
**Phase 2 이후:** 가드레일 컴파일, 관리 API/DAO, 액션 통제, 모델 티어, UI, 승인.

**2. Placeholder scan**

TBD/TODO 없음. 다만 두 곳에 **구현자 판단이 필요한 지점**을 명시했다:

- Task 4 Step 7의 `dispose_engine` — `lru_cache`에서 인스턴스를 꺼낼 수 없으므로
  `_engines` 리스트를 쓰는 최종 형태를 제시했다. placeholder 버전은 쓰지 않는다고
  명시했다.
- Task 6 Step 5의 `HTTPException` 핸들러 — `app.exception_handlers[AppError]` 재사용이
  FastAPI 버전에 따라 안 될 수 있다. 대안(응답 조립 함수 직접 임포트)과 **요구사항이
  응답 형태 단일화라는 것**을 명시했고, 테스트가 그것을 고정한다.

**3. Type consistency**

- `Mode`는 `contract.py`가 소유하고 `AuthenticationService`가 임포트한다. `application`이
  `contract`를 임포트하는 것은 계약이 전송 형식이 아니라 **이 BC의 용어**이기 때문이다.
  `contract.py`는 패키지 루트에 있어 어느 레이어에도 속하지 않는다.
- `ApiKeyRepository` Protocol의 시그니처는 `SqlAlchemyApiKeyRepository`,
  `CachedApiKeyRepository`, `_SessionScopedApiKeyRepository`, 테스트의 `StubRepository`·
  `CountingRepository`가 모두 동일하게 구현한다 — `find_by_hash`/`add` 두 개뿐이다.
- `hash_key`는 도메인이 소유하고 캐시·서비스·CLI가 임포트한다. 캐시 키가 해시라는
  성질이 한 곳에서 온다.
- `AuthenticatedRequest.mode`는 `Mode`이고 감사 이벤트에는 `str(mode)`로 들어간다
  (Phase 1c).
- `create_key`가 `session_factory: Callable`를 받는 것은 테스트가 세션 픅스처를 그대로
  넘기기 위함이다. 프로덕션 경로(`_run`)는 실제 팩토리를 쓴다.

---

## Execution Handoff

계획서를 `docs/superpowers/plans/2026-08-12-phase1b-gateway-foundation.md`에 저장했다.
Phase 1c(프록시 경로)는 별도 계획서로 작성한다.
