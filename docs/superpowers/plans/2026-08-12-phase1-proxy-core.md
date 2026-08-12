# Phase 1: 프록시 코어 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `base_url`만 교체하면 동작하는 투명 OpenAI 호환 프록시. 키 인증, 업스트림 크레덴셜 조회, ClickHouse 감사 로그까지. 가드레일 판정은 아직 없다.

**Architecture:** FastAPI가 `/v1/chat/completions`를 받아 `Authorization: Bearer gdv_...`로 앱을 식별하고, 그 키에 매인 업스트림 base_url/API 키로 httpx가 중계한다. 스트리밍은 SSE를 그대로 흘려보낸다. 요청당 감사 이벤트 1건을 논블로킹 큐에 넣고 배경 태스크가 ClickHouse에 배치 삽입한다. 응답 경로에 DB 접근이 없다 — 키 조회는 인메모리 TTL 캐시가 덮는다.

**Tech Stack:** FastAPI 0.141.1 · uvicorn 0.52.1 · httpx 0.28.1 · orjson 3.11.9 · SQLAlchemy 2.0.52 (async) · Alembic 1.19.1 · psycopg 3.3.4 (binary) · clickhouse-connect 1.7.0 · pydantic-settings · python-ulid · pytest · pytest-asyncio · respx · ruff · uv 0.11.7

**설계 문서:** `docs/superpowers/specs/2026-08-12-gardevoir-design.md`

---

## Global Constraints

프로젝트 전역 요구사항. 모든 태스크에 암묵적으로 포함된다.

- **Python 3.12** 이상. 개발 환경은 3.12.3 (aarch64).
- **패키지 관리는 `uv`만** 사용한다. `pip install` 직접 호출 금지.
- **JSON 직렬화/역직렬화는 `orjson`만** 사용한다. 표준 `json` 모듈은 테스트 픅스처 외에는 금지 (§11.7).
- **regex는 `google-re2`(`import re2`)만** 사용한다. 표준 `re`는 ReDoS에 취약하므로 사용자 입력이 닿는 경로에서 금지 (§11.1). Phase 1에는 패턴 매칭이 없지만 습관을 고정한다.
- **`DateTime64(3)` 컬럼에는 `datetime` 객체만** 삽입한다. unix 초를 int로 넣으면 밀리초로 해석되어 1970년에 조용히 저장된다 (§11.10).
- **`finish_reason`에는 표준 값만** 넣는다: `stop` / `length` / `tool_calls` / `content_filter` / `function_call`. 커스텀 값은 OpenAI SDK의 Literal 검증을 깨뜨린다 (§11.9).
- **확장 정보는 응답 최상위 `gardevoir` 키**에만 담는다 (§7.3).
- **감사 쓰기는 응답을 절대 막지 않는다** (§10).
- **헤더 접두사는 `X-Gardevoir-`**. 상관 ID는 표준 `X-Request-Id` (§7.2).
- 코드 주석과 커밋 메시지는 한국어, 식별자/독스트링은 영어.
- `ruff check`와 `ruff format --check`가 통과해야 커밋한다.

### 프로토콜 (§7.2) — Phase 1에서 전부 파싱하고 기록한다

판정 로직은 없지만 계약은 Phase 1에서 완성한다. 나중에 추가하면 배포된 앱이 깨진다.

| 요청 헤더 | 필수 | Phase 1 동작 |
|---|---|---|
| `Authorization: Bearer gdv_...` | ✅ | 키 조회 → 앱·허용 가드레일·업스트림 크레덴셜 |
| `X-Gardevoir-Guardrail` | — | 허용 목록 검증. 없으면 키 기본값 |
| `X-Gardevoir-Mode` | — | `enforce`(기본) / `dry-run`. 권한 검사 없음 |
| `X-Request-Id` | — | 감사 이벤트에 기록 |

| 응답 헤더 | Phase 1 값 |
|---|---|
| `X-Gardevoir-Action` | 항상 `allow` (판정 없음) |
| `X-Gardevoir-Guardrail` | 실제 적용된 가드레일 이름 |
| `X-Gardevoir-Guardrail-Version` | Phase 1은 `0` (컴파일된 가드레일 없음) |
| `X-Gardevoir-Mode` | 실제 적용된 모드 |
| `X-Gardevoir-Audit-Id` | 감사 이벤트 ULID |
| `X-Gardevoir-Latency-Ms` | 게이트웨이가 추가한 지연 (업스트림 대기 제외) |

---

## File Structure

```
pyproject.toml                      의존성, ruff/pytest 설정, 콘솔 스크립트
docker-compose.yml                  postgres:17-alpine + clickhouse 25.8-alpine
.env.example                        GARDEVOIR_* 환경변수 예시
alembic.ini                         Alembic 설정
migrations/                         Alembic (Postgres)
  env.py
  versions/
clickhouse/
  001_audit_events.sql              ClickHouse 스키마 (번호 .sql)

src/gardevoir/
  __init__.py
  config.py         Settings (pydantic-settings). 단일 진실의 출처
  contract.py       헤더 이름, Action/Mode enum, gardevoir 확장 객체 조립
  models.py         SQLAlchemy Base + ApiKey 모델
  db.py             async engine/sessionmaker 수명 관리
  auth.py           Bearer 파싱, 키 해시, ApiKeyContext 조회
  key_cache.py      TTL 인메모리 키 캐시 (핫패스에서 DB 제거)
  upstream.py       httpx 중계 — 비스트리밍 + 스트리밍
  audit/
    __init__.py
    event.py        AuditEvent 데이터클래스, ULID 생성
    schema.py       ClickHouse DDL 적용
    writer.py       큐 + 배치 삽입 + 임계 이벤트 동기 폴백
  proxy.py          /v1/chat/completions 라우트
  app.py            FastAPI 팩토리 + lifespan
  cli.py            gardevoir-migrate, gardevoir-createkey

tests/
  conftest.py       DB 픅스처, 앱 픅스처
  test_contract.py  SDK 확장 필드 회귀 테스트 (§11.9)
  test_auth.py
  test_key_cache.py
  test_upstream.py
  test_audit_writer.py
  test_proxy.py     E2E — OpenAI SDK를 앱에 직접 붙임
```

**경계 원칙:** `contract.py`는 와이어 계약만 담는다(§7의 "프로토콜은 최소, 설정은 최대"). `auth.py`는 조회만, `key_cache.py`는 캐싱만 — 캐시 정책을 조회 로직과 섞으면 테스트가 어려워진다. `audit/`은 감사 경로 전체를 담고 SQLAlchemy를 임포트하지 않는다(§12: 두 경로 완전 분리).

---

## Task 1: 프로젝트 스캐폴드 + Docker Compose + 설정

**Files:**
- Create: `pyproject.toml`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `src/gardevoir/__init__.py`
- Create: `src/gardevoir/config.py`
- Test: `tests/test_config.py`
- Test: `tests/conftest.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `gardevoir.config.Settings` — `postgres_dsn: str`, `clickhouse_host: str`, `clickhouse_port: int`, `clickhouse_user: str`, `clickhouse_password: str`, `clickhouse_database: str`, `upstream_timeout_s: float`, `audit_batch_size: int`, `audit_flush_interval_s: float`, `audit_queue_maxsize: int`, `key_cache_ttl_s: float`
  - `gardevoir.config.get_settings() -> Settings`

- [ ] **Step 1: `pyproject.toml` 작성**

```toml
[project]
name = "gardevoir"
version = "0.1.0"
description = "OpenAI-compatible guardrail proxy for LLM apps"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.141.1",
    "uvicorn[standard]>=0.52.1",
    "httpx>=0.28.1",
    "orjson>=3.11.9",
    "sqlalchemy[asyncio]>=2.0.52",
    "alembic>=1.19.1",
    "psycopg[binary,pool]>=3.3.4",
    "clickhouse-connect>=1.7.0",
    "pydantic-settings>=2.0",
    "python-ulid>=3.0",
    "google-re2>=1.1",
]

[project.scripts]
gardevoir-migrate = "gardevoir.cli:migrate"
gardevoir-createkey = "gardevoir.cli:createkey"

[dependency-groups]
dev = [
    "pytest>=9.1.1",
    "pytest-asyncio>=1.0",
    "respx>=0.23.1",
    "ruff>=0.8",
    "openai>=3.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gardevoir"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]
```

`openai`는 dev 의존성이다 — 런타임에 쓰지 않고 §11.9 회귀 테스트와 E2E 테스트에만 쓴다.

- [ ] **Step 2: `docker-compose.yml` 작성**

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: gardevoir
      POSTGRES_PASSWORD: gardevoir
      POSTGRES_DB: gardevoir
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gardevoir"]
      interval: 2s
      timeout: 3s
      retries: 20

  clickhouse:
    image: clickhouse/clickhouse-server:25.8-alpine
    environment:
      CLICKHOUSE_USER: gardevoir
      CLICKHOUSE_PASSWORD: gardevoir
      CLICKHOUSE_DB: gardevoir
    ports: ["8123:8123"]
    ulimits:
      nofile: { soft: 262144, hard: 262144 }
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:8123/ping || exit 1"]
      interval: 2s
      timeout: 3s
      retries: 20
```

`ulimits`는 ClickHouse가 기동 시 파일 디스크립터 한도를 경고하는 것을 막는다.

- [ ] **Step 3: `.env.example` 작성**

```
GARDEVOIR_POSTGRES_DSN=postgresql+psycopg://gardevoir:gardevoir@localhost:5432/gardevoir
GARDEVOIR_CLICKHOUSE_HOST=localhost
GARDEVOIR_CLICKHOUSE_PORT=8123
GARDEVOIR_CLICKHOUSE_USER=gardevoir
GARDEVOIR_CLICKHOUSE_PASSWORD=gardevoir
GARDEVOIR_CLICKHOUSE_DATABASE=gardevoir
GARDEVOIR_UPSTREAM_TIMEOUT_S=120.0
GARDEVOIR_AUDIT_BATCH_SIZE=100
GARDEVOIR_AUDIT_FLUSH_INTERVAL_S=1.0
GARDEVOIR_AUDIT_QUEUE_MAXSIZE=10000
GARDEVOIR_KEY_CACHE_TTL_S=30.0
```

- [ ] **Step 4: 실패하는 테스트 작성**

`tests/test_config.py`:

```python
from gardevoir.config import Settings, get_settings


def test_settings_reads_env_prefix(monkeypatch):
    monkeypatch.setenv("GARDEVOIR_POSTGRES_DSN", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("GARDEVOIR_CLICKHOUSE_HOST", "ch.example")
    get_settings.cache_clear()
    s = get_settings()
    assert s.postgres_dsn == "postgresql+psycopg://u:p@h:5432/d"
    assert s.clickhouse_host == "ch.example"


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("GARDEVOIR_POSTGRES_DSN", "postgresql+psycopg://u:p@h:5432/d")
    get_settings.cache_clear()
    s = get_settings()
    assert s.audit_batch_size == 100
    assert s.audit_flush_interval_s == 1.0
    assert s.audit_queue_maxsize == 10_000
    assert s.key_cache_ttl_s == 30.0
    assert s.upstream_timeout_s == 120.0


def test_settings_is_cached(monkeypatch):
    monkeypatch.setenv("GARDEVOIR_POSTGRES_DSN", "postgresql+psycopg://u:p@h:5432/d")
    get_settings.cache_clear()
    assert get_settings() is get_settings()
```

`tests/conftest.py` (이 태스크에서는 최소 골격만):

```python
import os

os.environ.setdefault(
    "GARDEVOIR_POSTGRES_DSN",
    "postgresql+psycopg://gardevoir:gardevoir@localhost:5432/gardevoir",
)
os.environ.setdefault("GARDEVOIR_CLICKHOUSE_HOST", "localhost")
os.environ.setdefault("GARDEVOIR_CLICKHOUSE_PORT", "8123")
os.environ.setdefault("GARDEVOIR_CLICKHOUSE_USER", "gardevoir")
os.environ.setdefault("GARDEVOIR_CLICKHOUSE_PASSWORD", "gardevoir")
os.environ.setdefault("GARDEVOIR_CLICKHOUSE_DATABASE", "gardevoir")
```

- [ ] **Step 5: 테스트 실패 확인**

```bash
uv sync
uv run pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gardevoir.config'`

- [ ] **Step 6: `config.py` 구현**

`src/gardevoir/__init__.py`:

```python
__all__ = ["__version__"]
__version__ = "0.1.0"
```

`src/gardevoir/config.py`:

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of truth for runtime configuration."""

    postgres_dsn: str

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "gardevoir"
    clickhouse_password: str = "gardevoir"
    clickhouse_database: str = "gardevoir"

    upstream_timeout_s: float = 120.0

    audit_batch_size: int = 100
    audit_flush_interval_s: float = 1.0
    audit_queue_maxsize: int = 10_000

    key_cache_ttl_s: float = 30.0

    model_config = SettingsConfigDict(
        env_prefix="GARDEVOIR_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 7: 테스트 통과 확인**

```bash
uv run pytest tests/test_config.py -v
uv run ruff check && uv run ruff format --check
```

Expected: 3 passed, ruff 통과

- [ ] **Step 8: 두 DB가 기동하는지 확인**

```bash
docker compose up -d
docker compose ps
```

Expected: `postgres`와 `clickhouse` 모두 `healthy`. 30초 이내.

```bash
curl -s -u gardevoir:gardevoir "http://localhost:8123/?query=SELECT+version()"
```

Expected: `25.8.x` 출력

- [ ] **Step 9: 커밋**

```bash
git add pyproject.toml uv.lock docker-compose.yml .env.example src/gardevoir tests
git commit -m "feat: 프로젝트 스캐폴드와 설정 계층

uv 기반 패키지 구성, Postgres 17 + ClickHouse 25.8 Docker Compose,
pydantic-settings 기반 Settings를 단일 진실의 출처로 둔다."
```

---

## Task 2: 와이어 계약 + SDK 확장 필드 회귀 테스트

계약을 먼저 고정한다. §7의 원칙("프로토콜은 최소, 설정은 최대")대로 이 모듈은 작게 유지되고, 여기에 무언가 추가하는 것은 되돌리기 어려운 결정임을 코드 위치로 표현한다.

**Files:**
- Create: `src/gardevoir/contract.py`
- Test: `tests/test_contract.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - 헤더 상수: `HEADER_GUARDRAIL`, `HEADER_MODE`, `HEADER_ACTION`, `HEADER_GUARDRAIL_VERSION`, `HEADER_AUDIT_ID`, `HEADER_LATENCY_MS`, `HEADER_REQUEST_ID` (모두 `str`)
  - `EXTENSION_KEY: str` = `"gardevoir"`
  - `class Action(StrEnum)`: `ALLOW`, `BLOCKED`, `APPROVAL_REQUIRED`
  - `class Mode(StrEnum)`: `ENFORCE`, `DRY_RUN`; `Mode.parse(raw: str | None) -> Mode`
  - `STANDARD_FINISH_REASONS: frozenset[str]`
  - `build_extension(*, action: Action, guardrail: str, guardrail_version: int, audit_id: str, mode: Mode, dry_run_would_have: dict | None = None) -> dict`
  - `response_headers(*, action: Action, guardrail: str, guardrail_version: int, mode: Mode, audit_id: str, latency_ms: float) -> dict[str, str]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_contract.py`:

```python
import orjson
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from gardevoir.contract import (
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


def test_mode_parse_defaults_to_enforce():
    assert Mode.parse(None) is Mode.ENFORCE
    assert Mode.parse("") is Mode.ENFORCE
    assert Mode.parse("enforce") is Mode.ENFORCE
    assert Mode.parse("dry-run") is Mode.DRY_RUN
    assert Mode.parse("DRY-RUN") is Mode.DRY_RUN
    assert Mode.parse("nonsense") is Mode.ENFORCE


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


def test_response_headers_are_all_strings():
    h = response_headers(
        action=Action.ALLOW,
        guardrail="doc-agent",
        guardrail_version=0,
        mode=Mode.ENFORCE,
        audit_id="evt_3",
        latency_ms=0.6183,
    )
    assert h[HEADER_ACTION] == "allow"
    assert h[HEADER_GUARDRAIL_VERSION] == "0"
    assert h[HEADER_LATENCY_MS] == "0.618"
    assert all(isinstance(v, str) for v in h.values())


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
        gardevoir={"action": "approval_required", "audit_id": "evt_4"},
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
        audit_id="evt_5",
        mode=Mode.ENFORCE,
    )
    payload = dict(_BASE_COMPLETION, **{EXTENSION_KEY: ext})
    restored = orjson.loads(orjson.dumps(payload))
    assert ChatCompletion.model_validate(restored).gardevoir["action"] == "blocked"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_contract.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gardevoir.contract'`

- [ ] **Step 3: `contract.py` 구현**

```python
"""The wire contract between gardevoir and client applications.

프로토콜은 최소로 유지한다. 여기에 항목을 추가하는 것은 배포된 앱을 깨뜨릴 수 있는
되돌리기 어려운 결정이다. 가변적인 것은 설정으로 뺀다. (설계 문서 §7)
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

#: 계약 버전은 URL 경로(/v1/)가 담당한다. 헤더로 두지 않는다. (설계 문서 §7.2)
API_PREFIX = "/v1"

#: OpenAI SDK가 Literal로 검증하는 값들. 이 밖의 값은 클라이언트를 깨뜨린다. (§11.9)
STANDARD_FINISH_REASONS = frozenset(
    {"stop", "length", "tool_calls", "content_filter", "function_call"}
)


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
    was silently enforced would believe it had tested safely. (§7.2)
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
uv run pytest tests/test_contract.py -v
uv run ruff check && uv run ruff format --check
```

Expected: 10 passed

- [ ] **Step 5: 커밋**

```bash
git add src/gardevoir/contract.py tests/test_contract.py
git commit -m "feat: 와이어 계약 정의와 SDK 확장 필드 회귀 테스트

헤더 이름, Action/Mode, gardevoir 확장 객체를 한 모듈에 고정한다.
openai SDK 3.0.0의 관용성을 테스트로 박아 SDK 업그레이드 시
확장 필드가 깨지면 즉시 드러나게 한다."
```

---

## Task 3: Postgres 모델 + Alembic + 키 조회

**Files:**
- Create: `src/gardevoir/models.py`
- Create: `src/gardevoir/db.py`
- Create: `src/gardevoir/auth.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/` (Alembic이 채운다)
- Modify: `tests/conftest.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `gardevoir.config.get_settings`, `Settings.postgres_dsn`
- Produces:
  - `gardevoir.models.Base` — SQLAlchemy `DeclarativeBase`
  - `gardevoir.models.ApiKey` — 컬럼: `id: str`(PK, ULID), `name: str`, `key_hash: str`(unique), `upstream_base_url: str`, `upstream_api_key: str`, `allowed_guardrails: list[str]`(JSONB), `default_guardrail: str | None`, `disabled: bool`, `created_at: datetime`
  - `gardevoir.db.Database` — `__init__(dsn: str)`, `async open() -> None`, `async close() -> None`, `session() -> AsyncSession` (async context manager)
  - `gardevoir.auth.ApiKeyContext` — frozen dataclass: `key_id: str`, `name: str`, `upstream_base_url: str`, `upstream_api_key: str`, `allowed_guardrails: tuple[str, ...]`, `default_guardrail: str | None`
  - `gardevoir.auth.hash_key(raw: str) -> str`
  - `gardevoir.auth.generate_key() -> str`
  - `gardevoir.auth.parse_bearer(header: str | None) -> str | None`
  - `gardevoir.auth.load_key_context(session: AsyncSession, raw_key: str) -> ApiKeyContext | None`
  - `gardevoir.auth.resolve_guardrail(ctx: ApiKeyContext, requested: str | None) -> str` — raises `GuardrailNotAllowed`
  - `gardevoir.auth.GuardrailNotAllowed` — Exception

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_auth.py`:

```python
import pytest

from gardevoir.auth import (
    ApiKeyContext,
    GuardrailNotAllowed,
    generate_key,
    hash_key,
    load_key_context,
    parse_bearer,
    resolve_guardrail,
)
from gardevoir.models import ApiKey


def test_generate_key_has_prefix_and_entropy():
    k1, k2 = generate_key(), generate_key()
    assert k1.startswith("gdv_live_")
    assert k1 != k2
    assert len(k1) > 40


def test_hash_key_is_stable_and_not_reversible():
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


def _ctx(allowed=("base", "doc-agent"), default="base") -> ApiKeyContext:
    return ApiKeyContext(
        key_id="k1",
        name="app",
        upstream_base_url="https://api.openai.com/v1",
        upstream_api_key="sk-x",
        allowed_guardrails=allowed,
        default_guardrail=default,
    )


def test_resolve_guardrail_uses_default_when_absent():
    assert resolve_guardrail(_ctx(), None) == "base"


def test_resolve_guardrail_accepts_allowed():
    assert resolve_guardrail(_ctx(), "doc-agent") == "doc-agent"


def test_resolve_guardrail_rejects_unallowed():
    with pytest.raises(GuardrailNotAllowed):
        resolve_guardrail(_ctx(), "internal-analytics")


def test_resolve_guardrail_falls_back_to_first_allowed_without_default():
    assert resolve_guardrail(_ctx(default=None), None) == "base"


async def test_load_key_context_roundtrip(db, session):
    raw = generate_key()
    session.add(
        ApiKey(
            id="k-test",
            name="test-app",
            key_hash=hash_key(raw),
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="sk-upstream",
            allowed_guardrails=["base", "doc-agent"],
            default_guardrail="base",
        )
    )
    await session.commit()

    ctx = await load_key_context(session, raw)
    assert ctx is not None
    assert ctx.key_id == "k-test"
    assert ctx.upstream_api_key == "sk-upstream"
    assert ctx.allowed_guardrails == ("base", "doc-agent")


async def test_load_key_context_rejects_unknown(db, session):
    assert await load_key_context(session, generate_key()) is None


async def test_load_key_context_rejects_disabled(db, session):
    raw = generate_key()
    session.add(
        ApiKey(
            id="k-off",
            name="off",
            key_hash=hash_key(raw),
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="sk-x",
            allowed_guardrails=["base"],
            default_guardrail="base",
            disabled=True,
        )
    )
    await session.commit()
    assert await load_key_context(session, raw) is None
```

`tests/conftest.py`에 추가 (Step 1의 기존 환경변수 블록 아래):

```python
import pytest_asyncio

from gardevoir.config import get_settings
from gardevoir.db import Database
from gardevoir.models import Base


@pytest_asyncio.fixture(scope="session")
async def db():
    """Session-scoped database with a freshly created schema.

    Requires `docker compose up -d postgres`.
    """
    database = Database(get_settings().postgres_dsn)
    await database.open()
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.close()


@pytest_asyncio.fixture
async def session(db):
    """Per-test session; every table is truncated afterwards."""
    async with db.session() as s:
        yield s
    async with db.engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.exec_driver_sql(f'TRUNCATE TABLE "{table.name}" CASCADE')
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
docker compose up -d postgres
uv run pytest tests/test_auth.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gardevoir.models'`

- [ ] **Step 3: `models.py` 구현**

```python
"""SQLAlchemy models for mutable state. Postgres only.

감사 이벤트는 여기에 없다 — ClickHouse로 분리되어 있고 이 모듈을 임포트하지
않는다. (설계 문서 §10, §12)
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    #: sha256 hex of the raw key. The raw key is never stored.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    upstream_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    upstream_api_key: Mapped[str] = mapped_column(String(512), nullable=False)

    #: Guardrails this key may select via X-Gardevoir-Guardrail. A request can
    #: never escape this set — that is why guardrail choice is bound to the
    #: credential rather than a header. (§7.2)
    allowed_guardrails: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    default_guardrail: Mapped[str | None] = mapped_column(String(255), nullable=True)

    disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: `db.py` 구현**

```python
"""Async engine and session lifecycle for Postgres."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class Database:
    """Owns the engine and sessionmaker. One instance per process."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    async def open(self) -> None:
        self._engine = create_async_engine(self._dsn, pool_pre_ping=True)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database.open() was not awaited")
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._sessionmaker is None:
            raise RuntimeError("Database.open() was not awaited")
        async with self._sessionmaker() as s:
            yield s
```

- [ ] **Step 5: `auth.py` 구현**

```python
"""API key authentication and guardrail resolution.

키는 고엔트로피 난수이므로 sha256으로 해시한다. bcrypt/argon2는 저엔트로피
사람 비밀번호를 위한 것이고, 요청마다 도는 경로에서는 너무 느리다.
"""

import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gardevoir.models import ApiKey

KEY_PREFIX = "gdv_live_"


class GuardrailNotAllowed(Exception):
    """Raised when a request selects a guardrail its key does not permit."""

    def __init__(self, requested: str, allowed: tuple[str, ...]) -> None:
        super().__init__(f"guardrail {requested!r} is not allowed for this key")
        self.requested = requested
        self.allowed = allowed


@dataclass(frozen=True, slots=True)
class ApiKeyContext:
    key_id: str
    name: str
    upstream_base_url: str
    upstream_api_key: str
    allowed_guardrails: tuple[str, ...]
    default_guardrail: str | None


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


async def load_key_context(session: AsyncSession, raw_key: str) -> ApiKeyContext | None:
    row = (
        await session.execute(
            select(ApiKey).where(ApiKey.key_hash == hash_key(raw_key), ApiKey.disabled.is_(False))
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return ApiKeyContext(
        key_id=row.id,
        name=row.name,
        upstream_base_url=row.upstream_base_url,
        upstream_api_key=row.upstream_api_key,
        allowed_guardrails=tuple(row.allowed_guardrails or ()),
        default_guardrail=row.default_guardrail,
    )


def resolve_guardrail(ctx: ApiKeyContext, requested: str | None) -> str:
    """Resolve the effective guardrail, never escaping the key's allowed set."""
    if requested:
        if requested not in ctx.allowed_guardrails:
            raise GuardrailNotAllowed(requested, ctx.allowed_guardrails)
        return requested
    if ctx.default_guardrail:
        return ctx.default_guardrail
    if ctx.allowed_guardrails:
        return ctx.allowed_guardrails[0]
    raise GuardrailNotAllowed("<default>", ctx.allowed_guardrails)
```

- [ ] **Step 6: Alembic 초기화와 마이그레이션 생성**

```bash
uv run alembic init -t async migrations
```

`alembic.ini`에서 `sqlalchemy.url` 줄을 삭제한다 (환경변수에서 읽으므로).

`migrations/env.py`의 상단 임포트 아래에 추가하고, `target_metadata = None`을 교체한다:

```python
from gardevoir.config import get_settings
from gardevoir.models import Base

config.set_main_option("sqlalchemy.url", get_settings().postgres_dsn)
target_metadata = Base.metadata
```

마이그레이션 생성:

```bash
uv run alembic revision --autogenerate -m "api_keys 테이블"
uv run alembic upgrade head
```

Expected: `api_keys` 테이블 생성. 확인:

```bash
docker compose exec postgres psql -U gardevoir -c '\d api_keys'
```

- [ ] **Step 7: 테스트 통과 확인**

```bash
uv run pytest tests/test_auth.py -v
uv run ruff check && uv run ruff format --check
```

Expected: 10 passed

- [ ] **Step 8: 커밋**

```bash
git add src/gardevoir/models.py src/gardevoir/db.py src/gardevoir/auth.py \
        alembic.ini migrations tests/conftest.py tests/test_auth.py
git commit -m "feat: API 키 모델과 인증, Alembic 마이그레이션

키는 sha256으로 해시해 저장하고 원본은 보관하지 않는다.
가드레일 선택을 키에 묶어 앱이 허용 집합을 벗어날 수 없게 한다."
```

---

## Task 4: 키 캐시 — 핫패스에서 DB 제거

설계 문서 §6은 "요청 경로에 DB도 네트워크도 없다"를 요구한다. 키 조회가 유일한 DB 접근이므로 TTL 캐시로 덮는다.

**Files:**
- Create: `src/gardevoir/key_cache.py`
- Test: `tests/test_key_cache.py`

**Interfaces:**
- Consumes: `gardevoir.db.Database`, `gardevoir.auth.load_key_context`, `gardevoir.auth.ApiKeyContext`
- Produces:
  - `gardevoir.key_cache.ApiKeyCache` — `__init__(db: Database, ttl_s: float = 30.0, *, clock: Callable[[], float] = time.monotonic)`, `async get(raw_key: str) -> ApiKeyContext | None`, `invalidate(raw_key: str) -> None`, `clear() -> None`, `hits: int`, `misses: int`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_key_cache.py`:

```python
from gardevoir.auth import generate_key, hash_key
from gardevoir.key_cache import ApiKeyCache
from gardevoir.models import ApiKey


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


async def _insert(session, raw: str, key_id: str = "k1", name: str = "app") -> None:
    session.add(
        ApiKey(
            id=key_id,
            name=name,
            key_hash=hash_key(raw),
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="sk-x",
            allowed_guardrails=["base"],
            default_guardrail="base",
        )
    )
    await session.commit()


async def test_second_lookup_is_a_cache_hit(db, session):
    raw = generate_key()
    await _insert(session, raw)
    cache = ApiKeyCache(db, ttl_s=30.0, clock=FakeClock())

    assert (await cache.get(raw)).key_id == "k1"
    assert (await cache.get(raw)).key_id == "k1"
    assert cache.misses == 1
    assert cache.hits == 1


async def test_entry_expires_after_ttl(db, session):
    raw = generate_key()
    await _insert(session, raw)
    clock = FakeClock()
    cache = ApiKeyCache(db, ttl_s=30.0, clock=clock)

    await cache.get(raw)
    clock.advance(31.0)
    await cache.get(raw)
    assert cache.misses == 2


async def test_unknown_key_is_negative_cached(db, session):
    cache = ApiKeyCache(db, ttl_s=30.0, clock=FakeClock())
    raw = generate_key()

    assert await cache.get(raw) is None
    assert await cache.get(raw) is None
    # 존재하지 않는 키로 반복 요청해도 DB를 다시 때리지 않는다 (DoS 완화)
    assert cache.misses == 1
    assert cache.hits == 1


async def test_invalidate_forces_reload(db, session):
    raw = generate_key()
    await _insert(session, raw)
    cache = ApiKeyCache(db, ttl_s=30.0, clock=FakeClock())

    await cache.get(raw)
    cache.invalidate(raw)
    await cache.get(raw)
    assert cache.misses == 2


async def test_cache_does_not_store_raw_key(db, session):
    raw = generate_key()
    await _insert(session, raw)
    cache = ApiKeyCache(db, ttl_s=30.0, clock=FakeClock())
    await cache.get(raw)

    # 캐시 키는 해시여야 한다. 원본 키가 메모리 구조에 남으면 덤프 시 유출된다.
    assert all(raw not in k for k in cache._entries)
    assert hash_key(raw) in cache._entries
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_key_cache.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gardevoir.key_cache'`

- [ ] **Step 3: `key_cache.py` 구현**

```python
"""In-memory API key cache.

설계 문서 §6은 요청 경로에 DB 접근이 없을 것을 요구한다. 키 조회가 유일한
DB 접근이므로 여기서 덮는다. 존재하지 않는 키도 캐싱한다 — 그러지 않으면
무효한 키를 반복 전송하는 것만으로 DB에 부하를 줄 수 있다.

캐시 키는 원본 키가 아니라 sha256 해시다. 프로세스 메모리 덤프에 원본
크레덴셜이 남지 않게 한다.
"""

import time
from collections.abc import Callable

from gardevoir.auth import ApiKeyContext, hash_key, load_key_context
from gardevoir.db import Database


class ApiKeyCache:
    def __init__(
        self,
        db: Database,
        ttl_s: float = 30.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._ttl_s = ttl_s
        self._clock = clock
        self._entries: dict[str, tuple[float, ApiKeyContext | None]] = {}
        self.hits = 0
        self.misses = 0

    async def get(self, raw_key: str) -> ApiKeyContext | None:
        digest = hash_key(raw_key)
        entry = self._entries.get(digest)
        now = self._clock()
        if entry is not None and entry[0] > now:
            self.hits += 1
            return entry[1]

        self.misses += 1
        async with self._db.session() as session:
            ctx = await load_key_context(session, raw_key)
        self._entries[digest] = (now + self._ttl_s, ctx)
        return ctx

    def invalidate(self, raw_key: str) -> None:
        self._entries.pop(hash_key(raw_key), None)

    def clear(self) -> None:
        self._entries.clear()
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_key_cache.py -v
uv run ruff check && uv run ruff format --check
```

Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/gardevoir/key_cache.py tests/test_key_cache.py
git commit -m "feat: TTL 키 캐시로 핫패스에서 DB 제거

캐시 키를 sha256 해시로 두어 메모리에 원본 크레덴셜이 남지 않게 한다.
존재하지 않는 키도 캐싱해 무효 키 반복 전송으로 DB에 부하를 주는 것을 막는다."
```

---

## Task 5: 업스트림 중계 — 비스트리밍

**Files:**
- Create: `src/gardevoir/upstream.py`
- Test: `tests/test_upstream.py`

**Interfaces:**
- Consumes: `Settings.upstream_timeout_s`
- Produces:
  - `gardevoir.upstream.UpstreamResult` — frozen dataclass: `status_code: int`, `headers: dict[str, str]`, `body: bytes`
  - `gardevoir.upstream.HOP_BY_HOP: frozenset[str]`
  - `gardevoir.upstream.Upstream` — `__init__(client: httpx.AsyncClient, timeout_s: float)`, `async complete(*, base_url: str, api_key: str, path: str, payload: bytes) -> UpstreamResult`
  - `gardevoir.upstream.filter_response_headers(headers) -> dict[str, str]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_upstream.py`:

```python
import httpx
import orjson
import pytest
import respx

from gardevoir.upstream import HOP_BY_HOP, Upstream, filter_response_headers


def test_filter_strips_hop_by_hop_and_encoding():
    raw = {
        "content-type": "application/json",
        "content-length": "123",
        "content-encoding": "gzip",
        "transfer-encoding": "chunked",
        "connection": "keep-alive",
        "x-request-id": "upstream-1",
    }
    out = filter_response_headers(raw)
    assert out == {"content-type": "application/json", "x-request-id": "upstream-1"}
    assert "content-length" in HOP_BY_HOP


@respx.mock
async def test_complete_forwards_payload_and_auth():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"id": "cmpl-1", "choices": []},
            headers={"content-type": "application/json", "content-length": "34"},
        )
    )
    payload = orjson.dumps({"model": "gpt-4o", "messages": []})

    async with httpx.AsyncClient() as client:
        up = Upstream(client, timeout_s=5.0)
        result = await up.complete(
            base_url="https://api.openai.com/v1",
            api_key="sk-upstream",
            path="/chat/completions",
            payload=payload,
        )

    assert result.status_code == 200
    assert orjson.loads(result.body)["id"] == "cmpl-1"
    # content-length는 우리가 다시 계산해야 하므로 걸러진다
    assert "content-length" not in result.headers
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer sk-upstream"
    assert sent.content == payload


@respx.mock
async def test_complete_preserves_upstream_error_status():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate limited"}})
    )
    async with httpx.AsyncClient() as client:
        up = Upstream(client, timeout_s=5.0)
        result = await up.complete(
            base_url="https://api.openai.com/v1",
            api_key="sk-x",
            path="/chat/completions",
            payload=b"{}",
        )
    assert result.status_code == 429
    assert orjson.loads(result.body)["error"]["message"] == "rate limited"


@respx.mock
async def test_complete_handles_trailing_slash_in_base_url():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={})
    )
    async with httpx.AsyncClient() as client:
        up = Upstream(client, timeout_s=5.0)
        await up.complete(
            base_url="https://api.openai.com/v1/",
            api_key="sk-x",
            path="/chat/completions",
            payload=b"{}",
        )
    assert route.called


@respx.mock
async def test_complete_raises_on_timeout():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=httpx.ReadTimeout("too slow")
    )
    async with httpx.AsyncClient() as client:
        up = Upstream(client, timeout_s=0.01)
        with pytest.raises(httpx.ReadTimeout):
            await up.complete(
                base_url="https://api.openai.com/v1",
                api_key="sk-x",
                path="/chat/completions",
                payload=b"{}",
            )
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_upstream.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gardevoir.upstream'`

- [ ] **Step 3: `upstream.py` 구현 (비스트리밍만)**

```python
"""Relay to the upstream LLM provider."""

from dataclasses import dataclass

import httpx

#: Headers that describe a specific connection or body encoding and must not be
#: forwarded — we re-frame the body, so lengths and encodings are ours to set.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "content-encoding",
    }
)


@dataclass(frozen=True, slots=True)
class UpstreamResult:
    status_code: int
    headers: dict[str, str]
    body: bytes


def filter_response_headers(headers) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


class Upstream:
    def __init__(self, client: httpx.AsyncClient, timeout_s: float) -> None:
        self._client = client
        self._timeout_s = timeout_s

    @staticmethod
    def _url(base_url: str, path: str) -> str:
        return base_url.rstrip("/") + "/" + path.lstrip("/")

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "application/json",
        }

    async def complete(
        self, *, base_url: str, api_key: str, path: str, payload: bytes
    ) -> UpstreamResult:
        response = await self._client.post(
            self._url(base_url, path),
            content=payload,
            headers=self._headers(api_key),
            timeout=self._timeout_s,
        )
        return UpstreamResult(
            status_code=response.status_code,
            headers=filter_response_headers(response.headers),
            body=response.content,
        )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_upstream.py -v
uv run ruff check && uv run ruff format --check
```

Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/gardevoir/upstream.py tests/test_upstream.py
git commit -m "feat: 업스트림 비스트리밍 중계

hop-by-hop 헤더와 content-encoding/length를 걸러낸다.
본문을 다시 조립하므로 길이와 인코딩은 우리가 정해야 한다."
```

---

## Task 6: 업스트림 중계 — 스트리밍

SSE를 그대로 흘려보낸다. Phase 1에는 홀드백이 없다 — 그건 Phase 4에서 판정이 붙을 때 들어간다. 다만 **바이트 경계와 무관하게 안전하게 중계**되어야 하고, 그 성질을 테스트로 고정한다.

**Files:**
- Modify: `src/gardevoir/upstream.py`
- Modify: `tests/test_upstream.py`

**Interfaces:**
- Consumes: Task 5의 `Upstream`
- Produces:
  - `Upstream.stream(*, base_url, api_key, path, payload) -> AsyncIterator[bytes]` — 첫 yield 이전에 `stream_meta`가 채워진다
  - `Upstream.open_stream(*, base_url, api_key, path, payload)` — async context manager, `(UpstreamStream)` 반환
  - `gardevoir.upstream.UpstreamStream` — `status_code: int`, `headers: dict[str, str]`, `async aiter() -> AsyncIterator[bytes]`

`open_stream`이 필요한 이유: 응답 헤더는 스트림 본문보다 **먼저** 확정되어야 한다(§7.2). 제너레이터 하나로는 첫 청크를 받기 전에 status/headers를 알 수 없다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_upstream.py`에 추가:

```python
def _sse(*chunks: str) -> bytes:
    return "".join(f"data: {c}\n\n" for c in chunks).encode()


@respx.mock
async def test_open_stream_exposes_status_and_headers_before_body():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=_sse('{"choices":[{"delta":{"content":"hi"}}]}', "[DONE]"),
            headers={"content-type": "text/event-stream", "content-length": "99"},
        )
    )
    async with httpx.AsyncClient() as client:
        up = Upstream(client, timeout_s=5.0)
        async with up.open_stream(
            base_url="https://api.openai.com/v1",
            api_key="sk-x",
            path="/chat/completions",
            payload=b"{}",
        ) as stream:
            # 본문을 읽기 전에 헤더가 확정되어 있어야 한다 (§7.2)
            assert stream.status_code == 200
            assert stream.headers["content-type"] == "text/event-stream"
            assert "content-length" not in stream.headers
            body = b"".join([c async for c in stream.aiter()])

    assert b"[DONE]" in body
    assert b'"content":"hi"' in body


@respx.mock
async def test_stream_relays_all_bytes_unchanged():
    payload = _sse(*[orjson.dumps({"i": i}).decode() for i in range(50)], "[DONE]")
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=payload, headers={"content-type": "text/event-stream"}
        )
    )
    async with httpx.AsyncClient() as client:
        up = Upstream(client, timeout_s=5.0)
        async with up.open_stream(
            base_url="https://api.openai.com/v1",
            api_key="sk-x",
            path="/chat/completions",
            payload=b"{}",
        ) as stream:
            got = b"".join([c async for c in stream.aiter()])
    assert got == payload


@respx.mock
async def test_open_stream_surfaces_upstream_error_status():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    async with httpx.AsyncClient() as client:
        up = Upstream(client, timeout_s=5.0)
        async with up.open_stream(
            base_url="https://api.openai.com/v1",
            api_key="sk-bad",
            path="/chat/completions",
            payload=b"{}",
        ) as stream:
            assert stream.status_code == 401
            body = b"".join([c async for c in stream.aiter()])
    assert b"bad key" in body


@respx.mock
async def test_stream_sets_accept_event_stream():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})
    )
    async with httpx.AsyncClient() as client:
        up = Upstream(client, timeout_s=5.0)
        async with up.open_stream(
            base_url="https://api.openai.com/v1",
            api_key="sk-x",
            path="/chat/completions",
            payload=b"{}",
        ) as stream:
            async for _ in stream.aiter():
                pass
    assert route.calls[0].request.headers["accept"] == "text/event-stream"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_upstream.py -k stream -v
```

Expected: FAIL — `AttributeError: 'Upstream' object has no attribute 'open_stream'`

- [ ] **Step 3: `upstream.py`에 스트리밍 추가**

파일 상단 임포트를 교체:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
```

`Upstream` 클래스에 다음을 추가:

```python
    @asynccontextmanager
    async def open_stream(
        self, *, base_url: str, api_key: str, path: str, payload: bytes
    ) -> AsyncIterator["UpstreamStream"]:
        """Open an upstream stream, exposing status and headers before the body.

        응답 헤더는 본문보다 먼저 전송되므로, 스트림을 시작하기 전에 확정되어야
        한다. 제너레이터 하나로는 첫 청크 이전에 status를 알 수 없어서 컨텍스트
        매니저로 분리한다. (설계 문서 §7.2)
        """
        headers = self._headers(api_key) | {"accept": "text/event-stream"}
        request = self._client.build_request(
            "POST",
            self._url(base_url, path),
            content=payload,
            headers=headers,
            timeout=self._timeout_s,
        )
        response = await self._client.send(request, stream=True)
        try:
            yield UpstreamStream(
                status_code=response.status_code,
                headers=filter_response_headers(response.headers),
                _response=response,
            )
        finally:
            await response.aclose()
```

파일 끝에 추가:

```python
@dataclass(slots=True)
class UpstreamStream:
    status_code: int
    headers: dict[str, str]
    _response: httpx.Response

    async def aiter(self) -> AsyncIterator[bytes]:
        """Yield raw body bytes.

        `aiter_bytes` decodes any content-encoding, which is why we strip
        `content-encoding` from the forwarded headers.
        """
        async for chunk in self._response.aiter_bytes():
            yield chunk
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_upstream.py -v
uv run ruff check && uv run ruff format --check
```

Expected: 9 passed

- [ ] **Step 5: 커밋**

```bash
git add src/gardevoir/upstream.py tests/test_upstream.py
git commit -m "feat: 업스트림 SSE 스트리밍 중계

응답 헤더가 본문보다 먼저 확정되어야 하므로 컨텍스트 매니저로 분리한다.
Phase 1은 바이트를 그대로 흘려보내고 홀드백은 Phase 4에서 붙인다."
```

---

## Task 7: 감사 이벤트 + ClickHouse 배치 라이터

**Files:**
- Create: `clickhouse/001_audit_events.sql`
- Create: `src/gardevoir/audit/__init__.py`
- Create: `src/gardevoir/audit/event.py`
- Create: `src/gardevoir/audit/schema.py`
- Create: `src/gardevoir/audit/writer.py`
- Create: `src/gardevoir/cli.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_audit_writer.py`

**Interfaces:**
- Consumes: `Settings.clickhouse_*`, `Settings.audit_batch_size`, `Settings.audit_flush_interval_s`, `Settings.audit_queue_maxsize`
- Produces:
  - `gardevoir.audit.event.AuditEvent` — dataclass, 필드는 §10 스키마와 1:1. `to_row() -> list`
  - `gardevoir.audit.event.new_event_id() -> str`
  - `gardevoir.audit.event.AUDIT_COLUMNS: list[str]`
  - `gardevoir.audit.schema.apply_clickhouse_schema(client, sql_dir: Path) -> list[str]`
  - `gardevoir.audit.writer.AuditWriter` — `__init__(client, *, batch_size, flush_interval_s, queue_maxsize)`, `async start()`, `async stop()`, `async submit(event)`, `dropped: int`, `written: int`
  - `gardevoir.audit.writer.CRITICAL_ACTIONS: frozenset[str]`

- [ ] **Step 1: ClickHouse 스키마 작성**

`clickhouse/001_audit_events.sql`:

```sql
CREATE TABLE IF NOT EXISTS audit_events (
    id                String,
    created_at        DateTime64(3),
    request_id        String,
    api_key_id        String,
    app_name          LowCardinality(String),
    guardrail         LowCardinality(String),
    guardrail_version UInt32,
    mode              LowCardinality(String),
    action            LowCardinality(String),
    checkpoint        LowCardinality(String),
    checks_fired      Array(LowCardinality(String)),
    verdicts          String,
    tier_reached      LowCardinality(String),
    tainted           UInt8,
    latency_ms        Float32,
    model             LowCardinality(String),
    prompt_tokens     UInt32,
    completion_tokens UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (app_name, created_at, id);
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_audit_writer.py`:

```python
import asyncio
import datetime as dt
import time

from gardevoir.audit.event import AuditEvent, new_event_id
from gardevoir.audit.writer import AuditWriter


def _event(action: str = "allow", **kw) -> AuditEvent:
    base = dict(
        id=new_event_id(),
        created_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
        request_id="req_1",
        api_key_id="k1",
        app_name="app_0",
        guardrail="base",
        guardrail_version=0,
        mode="enforce",
        action=action,
        checkpoint="input",
        checks_fired=[],
        verdicts="[]",
        tier_reached="rule",
        tainted=False,
        latency_ms=0.62,
        model="gpt-4o",
        prompt_tokens=10,
        completion_tokens=5,
    )
    base.update(kw)
    return AuditEvent(**base)


def test_new_event_id_is_sortable_and_unique():
    a, b = new_event_id(), new_event_id()
    assert a != b
    assert len(a) == 26
    assert sorted([b, a]) == [a, b] or a == b


def test_to_row_matches_column_order():
    from gardevoir.audit.event import AUDIT_COLUMNS

    ev = _event()
    row = ev.to_row()
    assert len(row) == len(AUDIT_COLUMNS)
    assert row[AUDIT_COLUMNS.index("action")] == "allow"
    assert row[AUDIT_COLUMNS.index("tainted")] == 0


def test_created_at_is_datetime_not_epoch_seconds():
    """§11.10 함정: DateTime64(3)에 unix 초를 넣으면 1970년에 조용히 저장된다."""
    row = _event().to_row()
    from gardevoir.audit.event import AUDIT_COLUMNS

    value = row[AUDIT_COLUMNS.index("created_at")]
    assert isinstance(value, dt.datetime)
    assert value.year >= 2026


async def test_writer_flushes_on_batch_size(ch_client, audit_table):
    w = AuditWriter(ch_client, batch_size=3, flush_interval_s=60.0, queue_maxsize=100)
    await w.start()
    for _ in range(3):
        await w.submit(_event())
    await w.stop()

    assert w.written == 3
    assert ch_client.query("SELECT count() FROM audit_events").result_rows[0][0] == 3


async def test_writer_flushes_on_interval(ch_client, audit_table):
    w = AuditWriter(ch_client, batch_size=1000, flush_interval_s=0.1, queue_maxsize=100)
    await w.start()
    await w.submit(_event())
    await asyncio.sleep(0.35)
    written_before_stop = w.written
    await w.stop()

    assert written_before_stop == 1


async def test_stop_drains_remaining_events(ch_client, audit_table):
    w = AuditWriter(ch_client, batch_size=1000, flush_interval_s=60.0, queue_maxsize=100)
    await w.start()
    for _ in range(7):
        await w.submit(_event())
    await w.stop()

    assert ch_client.query("SELECT count() FROM audit_events").result_rows[0][0] == 7


async def test_full_queue_drops_allow_but_keeps_blocked(ch_client, audit_table):
    w = AuditWriter(ch_client, batch_size=1000, flush_interval_s=60.0, queue_maxsize=2)
    # 배경 태스크를 시작하지 않아 큐가 비워지지 않는다
    await w.submit(_event("allow"))
    await w.submit(_event("allow"))

    await w.submit(_event("allow"))  # 큐가 꽉 찼으므로 버려진다
    assert w.dropped == 1

    await w.submit(_event("blocked"))  # 임계 이벤트는 동기 삽입으로 폴백
    assert w.dropped == 1
    assert ch_client.query(
        "SELECT count() FROM audit_events WHERE action='blocked'"
    ).result_rows[0][0] == 1


async def test_submit_never_raises_when_clickhouse_is_down(audit_table):
    class BrokenClient:
        def insert(self, *a, **kw):
            raise RuntimeError("clickhouse down")

    w = AuditWriter(BrokenClient(), batch_size=1, flush_interval_s=60.0, queue_maxsize=10)
    await w.start()
    await w.submit(_event("blocked"))  # 예외가 응답 경로로 새어나가면 안 된다
    await asyncio.sleep(0.2)
    await w.stop()


async def test_slow_insert_does_not_block_the_event_loop(audit_table):
    """clickhouse-connect은 동기다. to_thread로 감싸지 않으면 프록시 전체가 멈춘다."""

    class SlowClient:
        def insert(self, *a, **kw):
            time.sleep(0.5)

    w = AuditWriter(SlowClient(), batch_size=1, flush_interval_s=0.01, queue_maxsize=10)
    await w.start()
    await w.submit(_event())
    await asyncio.sleep(0.05)  # 삽입이 시작되도록 양보

    started = time.perf_counter()
    await asyncio.sleep(0.05)  # 루프가 자유롭다면 ~0.05초
    elapsed = time.perf_counter() - started
    await w.stop()

    assert elapsed < 0.25, "이벤트 루프가 동기 삽입에 막혔다"
```

`tests/conftest.py`에 추가:

```python
from pathlib import Path

import clickhouse_connect
import pytest

from gardevoir.audit.schema import apply_clickhouse_schema


@pytest.fixture(scope="session")
def ch_client():
    s = get_settings()
    return clickhouse_connect.get_client(
        host=s.clickhouse_host,
        port=s.clickhouse_port,
        username=s.clickhouse_user,
        password=s.clickhouse_password,
        database=s.clickhouse_database,
    )


@pytest.fixture
def audit_table(ch_client):
    """Fresh audit_events table per test."""
    ch_client.command("DROP TABLE IF EXISTS audit_events")
    apply_clickhouse_schema(ch_client, Path("clickhouse"))
    yield
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
docker compose up -d
uv run pytest tests/test_audit_writer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gardevoir.audit'`

- [ ] **Step 4: `audit/event.py` 구현**

```python
"""Audit event shape. Mirrors the ClickHouse audit_events schema 1:1."""

import datetime as dt
from dataclasses import dataclass

from ulid import ULID

AUDIT_COLUMNS = [
    "id",
    "created_at",
    "request_id",
    "api_key_id",
    "app_name",
    "guardrail",
    "guardrail_version",
    "mode",
    "action",
    "checkpoint",
    "checks_fired",
    "verdicts",
    "tier_reached",
    "tainted",
    "latency_ms",
    "model",
    "prompt_tokens",
    "completion_tokens",
]


def new_event_id() -> str:
    """ULID — time-ordered and unique, so ids sort by creation."""
    return str(ULID())


@dataclass(slots=True)
class AuditEvent:
    id: str
    created_at: dt.datetime
    request_id: str
    api_key_id: str
    app_name: str
    guardrail: str
    guardrail_version: int
    mode: str
    action: str
    checkpoint: str
    checks_fired: list[str]
    verdicts: str
    tier_reached: str
    tainted: bool
    latency_ms: float
    model: str
    prompt_tokens: int
    completion_tokens: int

    def to_row(self) -> list:
        """Row ordered to match AUDIT_COLUMNS.

        created_at must stay a datetime. Passing unix seconds as an int makes
        ClickHouse read them as milliseconds and store 1970 dates with no
        error at all. (설계 문서 §11.10)
        """
        return [
            self.id,
            self.created_at,
            self.request_id,
            self.api_key_id,
            self.app_name,
            self.guardrail,
            self.guardrail_version,
            self.mode,
            self.action,
            self.checkpoint,
            self.checks_fired,
            self.verdicts,
            self.tier_reached,
            1 if self.tainted else 0,
            self.latency_ms,
            self.model,
            self.prompt_tokens,
            self.completion_tokens,
        ]
```

- [ ] **Step 5: `audit/schema.py`와 `audit/__init__.py` 구현**

`src/gardevoir/audit/__init__.py`:

```python
from gardevoir.audit.event import AUDIT_COLUMNS, AuditEvent, new_event_id
from gardevoir.audit.writer import AuditWriter

__all__ = ["AUDIT_COLUMNS", "AuditEvent", "AuditWriter", "new_event_id"]
```

`src/gardevoir/audit/schema.py`:

```python
"""ClickHouse schema application.

Alembic은 Postgres 전용이다. ClickHouse는 번호를 붙인 .sql 파일을 순서대로
적용한다 — 감사 스키마는 append-only 테이블 하나뿐이라 마이그레이션 도구가
필요하지 않다.
"""

from pathlib import Path


def apply_clickhouse_schema(client, sql_dir: Path) -> list[str]:
    """Apply every .sql file in name order. Statements must be idempotent."""
    applied: list[str] = []
    for path in sorted(sql_dir.glob("*.sql")):
        for statement in path.read_text().split(";"):
            if statement.strip():
                client.command(statement)
        applied.append(path.name)
    return applied
```

- [ ] **Step 6: `audit/writer.py` 구현**

```python
"""Audit writer: queue in front, batched ClickHouse insert behind.

응답 경로를 절대 막지 않는다(§10). 배치는 ClickHouse의 요구사항이기도 하다 —
작은 삽입을 자주 하면 파트가 과도하게 생긴다.
"""

import asyncio
import contextlib
import logging

from gardevoir.audit.event import AUDIT_COLUMNS, AuditEvent

logger = logging.getLogger(__name__)

#: 감사의 존재 이유인 이벤트들. 큐가 꽉 차도 버리지 않는다. (§10)
CRITICAL_ACTIONS = frozenset({"blocked", "approval_required"})

_TABLE = "audit_events"


class AuditWriter:
    def __init__(
        self,
        client,
        *,
        batch_size: int,
        flush_interval_s: float,
        queue_maxsize: int,
    ) -> None:
        self._client = client
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._queue: asyncio.Queue[AuditEvent] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task | None = None
        self.dropped = 0
        self.written = 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the background task, then drain whatever is left. Idempotent."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        while batch := self._drain(self._batch_size):
            await asyncio.to_thread(self._flush, batch)

    async def submit(self, event: AuditEvent) -> None:
        """Enqueue without blocking. Never raises into the response path."""
        try:
            self._queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass

        if event.action in CRITICAL_ACTIONS:
            # 임계 이벤트는 버리지 않는다. 큐를 우회해 바로 삽입한다.
            # 이 요청 하나는 삽입을 기다리지만 이벤트 루프는 막지 않는다.
            await asyncio.to_thread(self._flush, [event])
        else:
            self.dropped += 1
            logger.warning("audit queue full; dropped %s event", event.action)

    async def _run(self) -> None:
        """Block on the queue, then take as much as the batch allows.

        큐가 비어 있으면 flush_interval_s만큼 기다리고, 이벤트가 하나라도
        들어오면 즉시 그것과 함께 쌓인 것을 모아 삽입한다. 한산할 때는 지연이
        낮고, 바쁠 때는 자연히 배치가 커진다.
        """
        while True:
            try:
                first = await asyncio.wait_for(
                    self._queue.get(), timeout=self._flush_interval_s
                )
            except TimeoutError:
                continue
            batch = [first, *self._drain(self._batch_size - 1)]
            await asyncio.to_thread(self._flush, batch)

    def _drain(self, limit: int) -> list[AuditEvent]:
        batch: list[AuditEvent] = []
        while len(batch) < limit:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    def _flush(self, batch: list[AuditEvent]) -> None:
        """Synchronous insert. Always call via asyncio.to_thread.

        clickhouse-connect의 클라이언트는 동기이므로 이벤트 루프에서 직접
        호출하면 삽입이 끝날 때까지 프록시 전체가 멈춘다. 100행 삽입이
        5~20ms인데 그것이 모든 진행 중인 요청에 얹힌다.
        """
        if not batch:
            return
        try:
            self._client.insert(
                _TABLE, [e.to_row() for e in batch], column_names=AUDIT_COLUMNS
            )
            self.written += len(batch)
        except Exception:
            self.dropped += len(batch)
            logger.exception("audit insert failed; dropped %d events", len(batch))
```

`_run`은 `_stopping`을 보지 않고 무한 루프를 돈다 — `stop()`이 `cancel()`로 끝내고 남은 것을 직접 비운다. 취소 지점이 `wait_for` 한 곳으로 모여서 배치가 반쯤 삽입된 상태로 죽는 경우가 없다.

- [ ] **Step 7: `cli.py` 구현**

```python
"""Operator entry points."""

import asyncio
from pathlib import Path

import clickhouse_connect

from gardevoir.audit.schema import apply_clickhouse_schema
from gardevoir.auth import generate_key, hash_key
from gardevoir.config import get_settings
from gardevoir.db import Database
from gardevoir.models import ApiKey, Base


def _ch_client():
    s = get_settings()
    return clickhouse_connect.get_client(
        host=s.clickhouse_host,
        port=s.clickhouse_port,
        username=s.clickhouse_user,
        password=s.clickhouse_password,
        database=s.clickhouse_database,
    )


def migrate() -> None:
    """Apply the ClickHouse audit schema. Postgres is handled by Alembic."""
    applied = apply_clickhouse_schema(_ch_client(), Path("clickhouse"))
    print("clickhouse applied:", ", ".join(applied) or "(none)")


def createkey() -> None:
    """Create an API key and print it once — it is not recoverable afterwards."""
    asyncio.run(_createkey())


async def _createkey() -> None:
    import os

    raw = generate_key()
    db = Database(get_settings().postgres_dsn)
    await db.open()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session() as session:
        session.add(
            ApiKey(
                id=str(__import__("ulid").ULID()),
                name=os.environ.get("GDV_KEY_NAME", "local-dev"),
                key_hash=hash_key(raw),
                upstream_base_url=os.environ.get(
                    "GDV_UPSTREAM_BASE_URL", "https://api.openai.com/v1"
                ),
                upstream_api_key=os.environ["GDV_UPSTREAM_API_KEY"],
                allowed_guardrails=["base"],
                default_guardrail="base",
            )
        )
        await session.commit()
    await db.close()
    print(raw)
```

- [ ] **Step 8: 테스트 통과 확인**

```bash
uv run pytest tests/test_audit_writer.py -v
uv run ruff check && uv run ruff format --check
```

Expected: 9 passed

- [ ] **Step 9: 스키마 적용 확인**

```bash
uv run gardevoir-migrate
docker compose exec clickhouse clickhouse-client -u gardevoir --password gardevoir \
  -d gardevoir -q "DESCRIBE audit_events" | head -5
```

Expected: `id String`, `created_at DateTime64(3)` 등 출력

- [ ] **Step 10: 커밋**

```bash
git add clickhouse src/gardevoir/audit src/gardevoir/cli.py \
        tests/conftest.py tests/test_audit_writer.py
git commit -m "feat: ClickHouse 감사 이벤트와 배치 라이터

응답을 막지 않는 큐 + 배치 삽입. 큐가 꽉 차면 allow는 버리고
blocked/approval_required는 동기 삽입으로 폴백한다.
created_at은 datetime만 허용 — unix 초를 넣으면 1970년에 조용히 저장된다."
```

---

## Task 8: 프록시 라우트 조립 + E2E

Phase 1의 인수 기준: **OpenAI SDK가 `base_url`만 바꿔서 정상 동작한다.**

**Files:**
- Create: `src/gardevoir/proxy.py`
- Create: `src/gardevoir/app.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_proxy.py`

**Interfaces:**
- Consumes: 앞선 모든 태스크
- Produces:
  - `gardevoir.app.create_app(settings: Settings | None = None) -> FastAPI`
  - `app.state.db: Database`, `app.state.key_cache: ApiKeyCache`, `app.state.upstream: Upstream`, `app.state.audit: AuditWriter`
  - `gardevoir.proxy.router: APIRouter` — `POST /v1/chat/completions`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_proxy.py`:

```python
import httpx
import orjson
import pytest
import respx
from openai import AsyncOpenAI

from gardevoir.auth import generate_key, hash_key
from gardevoir.contract import (
    HEADER_ACTION,
    HEADER_AUDIT_ID,
    HEADER_GUARDRAIL,
    HEADER_GUARDRAIL_VERSION,
    HEADER_LATENCY_MS,
    HEADER_MODE,
)
from gardevoir.models import ApiKey

UPSTREAM = "https://api.openai.com/v1"


@pytest.fixture
async def api_key(session):
    raw = generate_key()
    session.add(
        ApiKey(
            id="k-proxy",
            name="proxy-test",
            key_hash=hash_key(raw),
            upstream_base_url=UPSTREAM,
            upstream_api_key="sk-upstream",
            allowed_guardrails=["base", "doc-agent"],
            default_guardrail="base",
        )
    )
    await session.commit()
    return raw


def _completion(content: str = "hello") -> dict:
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "logprobs": None,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }


async def test_missing_authorization_is_401(client):
    r = await client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": []})
    assert r.status_code == 401


async def test_unknown_key_is_401(client):
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": []},
        headers={"authorization": f"Bearer {generate_key()}"},
    )
    assert r.status_code == 401


@respx.mock
async def test_unallowed_guardrail_is_403(client, api_key):
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": []},
        headers={"authorization": f"Bearer {api_key}", HEADER_GUARDRAIL: "internal-analytics"},
    )
    assert r.status_code == 403


@respx.mock
async def test_relays_and_sets_contract_headers(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"authorization": f"Bearer {api_key}", "x-request-id": "req-abc"},
    )
    assert r.status_code == 200
    assert r.headers[HEADER_ACTION] == "allow"
    assert r.headers[HEADER_GUARDRAIL] == "base"
    assert r.headers[HEADER_GUARDRAIL_VERSION] == "0"
    assert r.headers[HEADER_MODE] == "enforce"
    assert len(r.headers[HEADER_AUDIT_ID]) == 26
    assert float(r.headers[HEADER_LATENCY_MS]) >= 0

    body = orjson.loads(r.content)
    assert body["choices"][0]["message"]["content"] == "hello"
    assert body["gardevoir"]["action"] == "allow"
    assert body["gardevoir"]["audit_id"] == r.headers[HEADER_AUDIT_ID]


@respx.mock
async def test_dry_run_is_echoed(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": []},
        headers={"authorization": f"Bearer {api_key}", HEADER_MODE: "dry-run"},
    )
    assert r.headers[HEADER_MODE] == "dry-run"
    assert orjson.loads(r.content)["gardevoir"]["dry_run"] is True


@respx.mock
async def test_streaming_relays_sse(client, api_key, audit_table):
    sse = (
        b'data: {"id":"c","object":"chat.completion.chunk","created":1,"model":"gpt-4o",'
        b'"choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})
    )
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [], "stream": True},
        headers={"authorization": f"Bearer {api_key}"},
    ) as r:
        assert r.status_code == 200
        # 스트리밍에서 Action은 입력 단계까지의 판정만 뜻한다 (§7.2)
        assert r.headers[HEADER_ACTION] == "allow"
        assert HEADER_AUDIT_ID in r.headers
        got = b"".join([c async for c in r.aiter_bytes()])
    assert b'"content":"hi"' in got
    assert b"[DONE]" in got


@respx.mock
async def test_upstream_error_status_is_preserved(client, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": []},
        headers={"authorization": f"Bearer {api_key}"},
    )
    assert r.status_code == 429


@respx.mock
async def test_audit_event_is_recorded(client, api_key, audit_table, app):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion())
    )
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": []},
        headers={"authorization": f"Bearer {api_key}", "x-request-id": "req-audit"},
    )
    await app.state.audit.stop()

    rows = app.state.ch.query(
        "SELECT id, request_id, api_key_id, action, prompt_tokens, completion_tokens "
        "FROM audit_events"
    ).result_rows
    assert len(rows) == 1
    assert rows[0][0] == r.headers[HEADER_AUDIT_ID]
    assert rows[0][1] == "req-audit"
    assert rows[0][2] == "k-proxy"
    assert rows[0][3] == "allow"
    assert rows[0][4] == 11
    assert rows[0][5] == 3


# --- Phase 1 인수 기준: OpenAI SDK가 base_url만 바꿔서 동작한다 ---------------


@respx.mock
async def test_openai_sdk_works_with_base_url_swap_only(app, api_key, audit_table):
    respx.post(f"{UPSTREAM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion("드롭인 동작"))
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gardevoir") as http:
        oai = AsyncOpenAI(base_url="http://gardevoir/v1", api_key=api_key, http_client=http)
        resp = await oai.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
        )
    assert resp.choices[0].message.content == "드롭인 동작"
    # 확장 필드가 SDK를 통과해 노출된다 (§11.9)
    assert resp.gardevoir["action"] == "allow"
```

`tests/conftest.py`에 추가:

```python
from gardevoir.app import create_app


@pytest_asyncio.fixture
async def app(db, ch_client):
    application = create_app()
    async with application.router.lifespan_context(application):
        # 테스트는 세션 스코프 DB/ClickHouse를 재사용한다
        application.state.db = db
        application.state.ch = ch_client
        application.state.key_cache.clear()
        yield application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

`tests/conftest.py` 상단에 `import httpx`를 추가한다.

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_proxy.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'gardevoir.app'`

- [ ] **Step 3: `proxy.py` 구현**

```python
"""The /v1/chat/completions route.

Phase 1은 판정이 없어 항상 allow다. 그러나 계약(헤더·확장 객체·감사)은
여기서 완성한다 — 나중에 추가하면 배포된 앱이 깨진다. (설계 문서 §7)
"""

import datetime as dt
import time

import orjson
from fastapi import APIRouter, Request
from fastapi.responses import ORJSONResponse, StreamingResponse

from gardevoir.audit.event import AuditEvent, new_event_id
from gardevoir.auth import GuardrailNotAllowed, parse_bearer, resolve_guardrail
from gardevoir.contract import (
    EXTENSION_KEY,
    HEADER_GUARDRAIL,
    HEADER_MODE,
    HEADER_REQUEST_ID,
    Action,
    Mode,
    build_extension,
    response_headers,
)

router = APIRouter()

#: Phase 1에는 컴파일된 가드레일이 없다. Phase 2에서 실제 버전이 들어간다.
PHASE1_GUARDRAIL_VERSION = 0

_UPSTREAM_PATH = "/chat/completions"


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    started = time.perf_counter()
    state = request.app.state

    raw_key = parse_bearer(request.headers.get("authorization"))
    if raw_key is None:
        return _error(401, "missing_api_key", "Authorization: Bearer <key> is required")

    ctx = await state.key_cache.get(raw_key)
    if ctx is None:
        return _error(401, "invalid_api_key", "the provided API key is not valid")

    mode = Mode.parse(request.headers.get(HEADER_MODE))
    try:
        guardrail = resolve_guardrail(ctx, request.headers.get(HEADER_GUARDRAIL))
    except GuardrailNotAllowed as exc:
        return _error(403, "guardrail_not_allowed", str(exc))

    payload = await request.body()
    stream_requested = _wants_stream(payload)

    audit_id = new_event_id()
    request_id = request.headers.get(HEADER_REQUEST_ID, "")

    headers = response_headers(
        action=Action.ALLOW,
        guardrail=guardrail,
        guardrail_version=PHASE1_GUARDRAIL_VERSION,
        mode=mode,
        audit_id=audit_id,
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    extension = build_extension(
        action=Action.ALLOW,
        guardrail=guardrail,
        guardrail_version=PHASE1_GUARDRAIL_VERSION,
        audit_id=audit_id,
        mode=mode,
    )

    async def record(*, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        await state.audit.submit(
            AuditEvent(
                id=audit_id,
                created_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
                request_id=request_id,
                api_key_id=ctx.key_id,
                app_name=ctx.name,
                guardrail=guardrail,
                guardrail_version=PHASE1_GUARDRAIL_VERSION,
                mode=str(mode),
                action=str(Action.ALLOW),
                checkpoint="",
                checks_fired=[],
                verdicts="[]",
                tier_reached="",
                tainted=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )

    if stream_requested:
        return await _relay_stream(state, ctx, payload, headers, extension, record)
    return await _relay_once(state, ctx, payload, headers, extension, record)


async def _relay_once(state, ctx, payload, headers, extension, record):
    result = await state.upstream.complete(
        base_url=ctx.upstream_base_url,
        api_key=ctx.upstream_api_key,
        path=_UPSTREAM_PATH,
        payload=payload,
    )
    body = _decode(result.body)
    if isinstance(body, dict):
        body[EXTENSION_KEY] = extension
    usage = body.get("usage") or {} if isinstance(body, dict) else {}
    await record(
        model=(body.get("model") if isinstance(body, dict) else "") or "",
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )
    return ORJSONResponse(
        content=body,
        status_code=result.status_code,
        headers=headers | {"content-type": "application/json"},
    )


async def _relay_stream(state, ctx, payload, headers, extension, record):
    """Relay SSE.

    응답 헤더는 본문보다 먼저 나가므로 스트림을 열어 status를 확정한 뒤
    StreamingResponse를 만든다. 스트리밍에서 X-Gardevoir-Action은 입력
    단계까지의 판정만 뜻한다. (설계 문서 §7.2)
    """
    cm = state.upstream.open_stream(
        base_url=ctx.upstream_base_url,
        api_key=ctx.upstream_api_key,
        path=_UPSTREAM_PATH,
        payload=payload,
    )
    stream = await cm.__aenter__()

    async def body_iter():
        try:
            async for chunk in stream.aiter():
                yield chunk
            yield b"data: " + orjson.dumps({EXTENSION_KEY: extension}) + b"\n\n"
        finally:
            await cm.__aexit__(None, None, None)
            await record(model="", prompt_tokens=0, completion_tokens=0)

    return StreamingResponse(
        body_iter(),
        status_code=stream.status_code,
        headers=headers,
        media_type=stream.headers.get("content-type", "text/event-stream"),
    )


def _wants_stream(payload: bytes) -> bool:
    body = _decode(payload)
    return bool(isinstance(body, dict) and body.get("stream"))


def _decode(payload: bytes):
    try:
        return orjson.loads(payload)
    except orjson.JSONDecodeError:
        return None


def _error(status: int, code: str, message: str) -> ORJSONResponse:
    return ORJSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "code": code}},
        status_code=status,
    )
```

- [ ] **Step 4: `app.py` 구현**

```python
"""FastAPI application factory."""

from contextlib import asynccontextmanager

import clickhouse_connect
import httpx
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from gardevoir.audit.writer import AuditWriter
from gardevoir.config import Settings, get_settings
from gardevoir.db import Database
from gardevoir.key_cache import ApiKeyCache
from gardevoir.proxy import router
from gardevoir.upstream import Upstream


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.postgres_dsn)
        await db.open()

        ch = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
        )
        audit = AuditWriter(
            ch,
            batch_size=settings.audit_batch_size,
            flush_interval_s=settings.audit_flush_interval_s,
            queue_maxsize=settings.audit_queue_maxsize,
        )
        await audit.start()

        client = httpx.AsyncClient()

        app.state.db = db
        app.state.ch = ch
        app.state.audit = audit
        app.state.key_cache = ApiKeyCache(db, ttl_s=settings.key_cache_ttl_s)
        app.state.upstream = Upstream(client, timeout_s=settings.upstream_timeout_s)
        try:
            yield
        finally:
            await audit.stop()
            await client.aclose()
            await db.close()

    app = FastAPI(
        title="gardevoir",
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )
    app.include_router(router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
docker compose up -d
uv run pytest tests/test_proxy.py -v
```

Expected: 9 passed

`test_audit_event_is_recorded`에서 `app.state.key_cache`가 세션 DB를 참조해야 한다. 실패하면 conftest의 `app` 픅스처가 `application.state.key_cache = ApiKeyCache(db, ttl_s=...)`로 재생성하도록 고칠 것.

- [ ] **Step 6: 전체 테스트와 린트**

```bash
uv run pytest -v
uv run ruff check && uv run ruff format --check
```

Expected: 모든 테스트 통과

- [ ] **Step 7: 실제 기동 확인**

```bash
uv run alembic upgrade head
uv run gardevoir-migrate
GDV_UPSTREAM_API_KEY=sk-dummy uv run gardevoir-createkey
uv run uvicorn --factory gardevoir.app:create_app --port 8080 &
sleep 2
curl -s localhost:8080/healthz
curl -si -X POST localhost:8080/v1/chat/completions \
  -H "authorization: Bearer <위에서 출력된 키>" \
  -H "content-type: application/json" \
  -d '{"model":"gpt-4o","messages":[]}' | head -12
kill %1
```

Expected: `/healthz`는 `{"status":"ok"}`. 프록시 호출은 업스트림 키가 더미이므로 401을 중계하되, `X-Gardevoir-Action`·`X-Gardevoir-Audit-Id` 헤더가 붙어 있어야 한다.

- [ ] **Step 8: 커밋**

```bash
git add src/gardevoir/proxy.py src/gardevoir/app.py tests/conftest.py tests/test_proxy.py
git commit -m "feat: 프록시 라우트와 앱 팩토리

/v1/chat/completions 비스트리밍·스트리밍 중계 완성.
Phase 1은 판정이 없어 항상 allow지만 계약(헤더·확장 객체·감사)은 여기서
완성한다 — 나중에 추가하면 배포된 앱이 깨진다.

인수 기준 통과: OpenAI SDK가 base_url 교체만으로 동작하고
확장 필드가 SDK를 통과해 노출된다."
```

---

## Self-Review

**1. Spec coverage (Phase 1 범위 대비)**

| 스펙 요구사항 | 태스크 |
|---|---|
| `/v1/chat/completions` 통과 | Task 5, 8 |
| 스트리밍 중계 | Task 6, 8 |
| 키 인증 | Task 3 |
| 인메모리 키 캐시 (§6 "핫패스에 DB 없음") | Task 4 |
| 업스트림 크레덴셜 조회 | Task 3, 8 |
| PostgreSQL + Alembic | Task 3 |
| ClickHouse 감사 로그 (§10) | Task 7 |
| 요청 헤더 4종 파싱 (§7.2) | Task 2, 8 |
| 응답 헤더 6종 (§7.2) | Task 2, 8 |
| `gardevoir` 확장 객체 (§7.3) | Task 2, 8 |
| 표준 `finish_reason`만 (§11.9) | Task 2 (회귀 테스트) |
| 감사가 응답을 막지 않음 (§10) | Task 7 |
| 임계 이벤트 미유실 (§10) | Task 7 |
| `DateTime64(3)` 함정 (§11.10) | Task 7 |
| 스트리밍 헤더 의미 차이 (§7.2) | Task 8 (테스트 주석 + 코드 주석) |
| dry-run 에코 (§7.2) | Task 2, 8 |
| `base_url` 교체 인수 기준 | Task 8 |

**Phase 1 범위 밖 (의도적 제외):** 가드레일 컴파일(Phase 2), 액션 통제(Phase 3), 모델 티어(Phase 4), 홀드백(Phase 4), UI(Phase 5), 승인(Phase 6).

**2. Placeholder scan**

TBD/TODO 없음. 모든 코드 스텝에 실제 코드가 있다. 자체 검토에서 고친 것:

- `docker-compose.yml`의 오타를 제거하고 ClickHouse `ulimits`를 추가했다.
- `AuditWriter._run`의 대기 로직을 `asyncio.wait_for(queue.get(), timeout=...)` 기반으로
  확정했다. 처음 쓴 `sleep` 기반 구현은 `test_writer_flushes_on_interval`과
  `test_writer_flushes_on_batch_size`를 동시에 만족하지 못했다.
- **`_flush`를 `asyncio.to_thread`로 감쌌다.** `clickhouse-connect` 클라이언트는 동기이므로
  이벤트 루프에서 직접 호출하면 삽입이 끝날 때까지 프록시 전체가 멈춘다. 100행 5~20ms가
  진행 중인 모든 요청에 얹혀 §11.8의 0.63ms 주장과 정면 충돌한다.
  `test_slow_insert_does_not_block_the_event_loop`로 이 성질을 고정했다.
- `AuditWriter.stop()`을 멱등으로 만들었다 — `test_audit_event_is_recorded`가 명시적으로
  호출하고 `app` 픅스처의 lifespan 종료가 다시 호출한다.

**3. Type consistency 확인**

- `Action`/`Mode`는 `StrEnum`이므로 `str(action)`이 값 문자열을 준다. `contract.py`, `proxy.py`, `audit/event.py`에서 일관.
- `AUDIT_COLUMNS`의 순서와 `AuditEvent.to_row()`의 순서가 1:1이고 `clickhouse/001_audit_events.sql`의 컬럼 순서와도 일치한다. Task 7의 `test_to_row_matches_column_order`가 이를 고정.
- `Upstream.complete`와 `Upstream.open_stream`이 같은 `path=` 파라미터 이름을 쓴다. `proxy.py`의 `_UPSTREAM_PATH`가 양쪽에 쓰인다.
- `ApiKeyContext.name`을 감사의 `app_name`으로 쓴다 — Task 3의 `ApiKey.name` → Task 8의 `AuditEvent.app_name`. 이름이 다르므로 Task 8 코드에 `app_name=ctx.name`으로 명시했다.
- `Database.session()`은 async context manager다. `key_cache.py`와 conftest에서 `async with`로 일관되게 쓴다.
- `ApiKeyCache.__init__`의 `ttl_s`는 위치·키워드 모두 허용, `clock`은 키워드 전용. 테스트와 `app.py` 모두 이에 맞다.

---

## Execution Handoff

Phase 1 계획서를 `docs/superpowers/plans/2026-08-12-phase1-proxy-core.md`에 저장했다.
