# Phase 1a: 워크스페이스 + shared_kernel 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **REQUIRED READING:** `skills/gardevoir-be/SKILL.md` before any step.

**Goal:** uv 워크스페이스와 `shared_kernel` 패키지를 세워, Phase 1b의 gateway BC가 얹힐 토대를 만든다.

**Architecture:** `backend/`가 가상 워크스페이스 루트이고 각 BC가 멤버다. `shared_kernel`이 첫 멤버로, 설정·예외·API 스키마·로깅의 교차 관심사를 담는다. clic의 `shared_kernel`을 재사용할 수 없으므로(사설 저장소) 필요한 절반만 새로 구현한다.

**Tech Stack:** uv 0.11.7 · Python 3.12 · pydantic-settings · SQLAlchemy 2.0.52 (async) · FastAPI 0.141.1 · pytest · ruff

**설계 문서:** `docs/superpowers/specs/2026-08-12-gardevoir-design.md`
**컨벤션:** `skills/gardevoir-be/SKILL.md`

---

## Global Constraints

- **Python 3.12** 이상.
- **패키지 관리는 `uv`만.** `pip install` 직접 호출 금지.
- **JSON은 `orjson`만.** 표준 `json`은 테스트 픅스처 외 금지.
- **regex는 `re2`만.** 표준 `re` 금지.
- 코드 주석·커밋 메시지는 한국어, 식별자·독스트링은 영어.
- `ruff check`와 `ruff format --check`가 통과해야 커밋한다.
- 제네릭은 PEP 695 문법(`class Page[T]`)을 쓴다. `Generic[T]`는 ruff UP046에 걸린다.
- BC 테스트는 그 패키지 디렉토리에서 실행한다: `cd backend/<bc> && uv run pytest`.
  `backend/`에서 맨 `pytest`를 돌리면 형제 패키지를 교차 수집한다.
- `shared_kernel`은 **실제로 쓰는 것만** 담는다. clic에 있다는 이유로 옮기지 않는다.

### 로컬 환경 제약 (실측)

이 머신은 이미 컨테이너 17개를 돌리고 있다 — clic 스택, envector 스택, vLLM 2개
(Qwen3-VL-30B, BGE-M3)로 메모리 89Gi가 사용 중이고 31Gi가 가용이다. 따라서:

- **기본 포트를 쓰지 않는다.** 이 머신의 기존 규칙이다 —
  spark-inference는 10000번대, envector는 18090/50070, clic은 20000–20070을 쓴다.
  gardevoir는 **21000 블록**을 쓴다.

  | 포트 | 용도 |
  |---|---|
  | 21000 | gateway HTTP |
  | 21010 | PostgreSQL |
  | 21020 | ClickHouse HTTP |
  | 21050 | console (Next.js, Phase 5) |

- **컨테이너마다 자원 상한을 건다.** clic의 "local runtime guardrails" 방식을 따른다.
  `MEMSWAP_LIMIT`을 `MEM_LIMIT`과 같게 두면 컨테이너가 예산을 넘어 스왑하지 못한다.
  실측 여유: ClickHouse 2GiB 상한에 426 MiB(20.8%), Postgres 512MiB 상한에 35 MiB(6.9%).

- 포트와 자원 상한은 `infra/envs/<dir>/compose.env`에 두고
  `docker compose --env-file`로 주입한다. compose 파일에 숫자를 박지 않는다.

> ⚠️ **컨테이너 헬스체크는 `localhost`가 아니라 `127.0.0.1`을 써야 한다.**
> 컨테이너의 `/etc/hosts`는 `localhost`를 `127.0.0.1`과 `::1` 둘 다에 매핑하고
> `wget`은 `::1`을 먼저 시도한다. ClickHouse는 `0.0.0.0:8123`(IPv4)만 듣기 때문에
> `localhost`로는 `Connection refused`가 무한 반복되고 `docker compose up --wait`가
> 끝나지 않는다. **에러 메시지가 원인을 가리키지 않는다.**
> Postgres는 `pg_isready`가 기본적으로 유닉스 소켓을 쓰므로 영향이 없다.

> ⚠️ **헬스 상태 판정에 `grep healthy`를 쓰지 않는다.** `unhealthy`도 매치된다.
> `docker inspect <c> --format '{{.State.Health.Status}}'`로 정확히 비교한다.

---

## File Structure

```
backend/
├── pyproject.toml                     워크스페이스 루트 (package=false)
├── .python-version
└── shared_kernel/
    ├── pyproject.toml
    ├── shared_kernel/
    │   ├── __init__.py
    │   ├── config/
    │   │   ├── __init__.py
    │   │   └── settings.py            BaseAppSettings, DatabaseSettings, ClickHouseSettings, LogSettings
    │   ├── exception/
    │   │   ├── __init__.py
    │   │   ├── base.py                AppError + 카테고리 (422/404/401/403/409)
    │   │   ├── catalog.py             ErrorCatalog 베이스 enum
    │   │   ├── schema.py              ErrorResponse
    │   │   └── handlers.py            register_exception_handlers(app)
    │   ├── api/
    │   │   ├── __init__.py
    │   │   └── schema.py              CamelModel
    │   ├── database/
    │   │   ├── __init__.py
    │   │   └── base.py                Base (naming_convention), TimestampMixin
    │   └── log/
    │       ├── __init__.py
    │       ├── context.py             request_id ContextVar
    │       ├── middleware.py          RequestContextMiddleware
    │       └── setup.py               configure_logging
    └── tests/
        ├── test_config.py
        ├── test_exception.py
        ├── test_handlers.py
        ├── test_api_schema.py
        └── test_log.py

infra/
├── README.md
├── docker-compose/
│   ├── postgres.yml
│   └── clickhouse.yml
└── envs/
    └── example/
        └── compose.env             포트 + 자원 상한
```

`shared_kernel`은 src 레이아웃을 쓰지 않는다 — clic과 동일하게 패키지 디렉토리가 루트에 바로 온다. BC(`gateway`)는 src 레이아웃을 쓴다.

---

## Task 1: uv 워크스페이스 + infra docker-compose

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.python-version`
- Create: `backend/shared_kernel/pyproject.toml`
- Create: `backend/shared_kernel/shared_kernel/__init__.py`
- Create: `infra/envs/example/compose.env`
- Create: `infra/docker-compose/postgres.yml`
- Create: `infra/docker-compose/clickhouse.yml`
- Create: `infra/README.md`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `shared_kernel` 워크스페이스 멤버가 `uv sync`로 설치되고 임포트된다.

- [ ] **Step 1: 워크스페이스 루트 작성**

`backend/pyproject.toml`:

```toml
[project]
name = "gardevoir-backend"
version = "0.0.0"
description = "gardevoir backend workspace root (virtual)"
requires-python = ">=3.12"

[tool.uv.workspace]
members = ["shared_kernel"]

[tool.uv.sources]
shared-kernel = { workspace = true }

[tool.uv]
package = false

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]
```

`backend/.python-version`:

```
3.12
```

- [ ] **Step 2: `shared_kernel` 멤버 작성**

`backend/shared_kernel/pyproject.toml`:

```toml
[project]
name = "shared-kernel"
version = "0.1.0"
description = "Cross-cutting building blocks shared by gardevoir bounded contexts"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.141.1",
    "sqlalchemy[asyncio]>=2.0.52",
    "pydantic>=2.13",
    "pydantic-settings>=2.3",
    "orjson>=3.11.9",
]

[dependency-groups]
dev = [
    "pytest>=9.1.1",
    "pytest-asyncio>=1.0",
    "httpx>=0.28.1",
    "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["shared_kernel"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`backend/shared_kernel/shared_kernel/__init__.py`:

```python
__all__ = ["__version__"]
__version__ = "0.1.0"
```

- [ ] **Step 3: `infra/envs/example/compose.env` 작성**

포트와 자원 상한은 여기서만 정한다. compose 파일에 숫자를 박지 않는다.

```
# 컨테이너 이름을 고정한다. 이게 없으면 -p 를 빼먹은 순간 프로젝트 이름이
# 디렉토리명에서 유추되고 헬스 판정(docker inspect gardevoir-postgres-1)이
# 조용히 깨진다.
COMPOSE_PROJECT_NAME=gardevoir

# 서비스별 env 파일이 필요해지면 compose에서
#   env_file: ../envs/${GARDEVOIR_ENV_DIR}/<svc>.env
# 로 참조한다. 현재 사용처 없음 — 전방 훅이다.
GARDEVOIR_ENV_DIR=example

# 21000 블록. 이 머신은 10000번대(spark-inference), 18090/50070(envector),
# 20000-20070(clic)이 이미 사용 중이다.
GATEWAY_HTTP_PORT=21000
POSTGRES_PORT=21010
CLICKHOUSE_HTTP_PORT=21020
CONSOLE_HTTP_PORT=21050

# 로컬 런타임 가드레일. MEMSWAP_LIMIT을 MEM_LIMIT과 같게 두면 컨테이너가
# 예산을 넘어 스왑하지 못한다. 실측 여유: ClickHouse 426MiB/2g, Postgres 35MiB/512m.
POSTGRES_MEM_LIMIT=512m
POSTGRES_MEMSWAP_LIMIT=512m
POSTGRES_CPUS=1.0
CLICKHOUSE_MEM_LIMIT=2g
CLICKHOUSE_MEMSWAP_LIMIT=2g
CLICKHOUSE_CPUS=2.0
```

- [ ] **Step 4: infra docker-compose 작성**

서비스별로 파일을 나눈다 — clic과 동일하게, 필요한 것만 조합해 띄울 수 있어야 한다.

`infra/docker-compose/postgres.yml`:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: gardevoir
      POSTGRES_PASSWORD: gardevoir
      POSTGRES_DB: gardevoir
    ports: ["${POSTGRES_PORT}:5432"]
    mem_limit: ${POSTGRES_MEM_LIMIT}
    memswap_limit: ${POSTGRES_MEMSWAP_LIMIT}
    cpus: ${POSTGRES_CPUS}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gardevoir"]
      interval: 2s
      timeout: 3s
      retries: 20
```

`infra/docker-compose/clickhouse.yml`:

```yaml
services:
  clickhouse:
    image: clickhouse/clickhouse-server:25.8-alpine
    environment:
      CLICKHOUSE_USER: gardevoir
      CLICKHOUSE_PASSWORD: gardevoir
      CLICKHOUSE_DB: gardevoir
    ports: ["${CLICKHOUSE_HTTP_PORT}:8123"]
    mem_limit: ${CLICKHOUSE_MEM_LIMIT}
    memswap_limit: ${CLICKHOUSE_MEMSWAP_LIMIT}
    cpus: ${CLICKHOUSE_CPUS}
    ulimits:
      nofile: { soft: 262144, hard: 262144 }
    healthcheck:
      # 127.0.0.1 이어야 한다. localhost는 ::1로 먼저 해석되고 ClickHouse는
      # IPv4만 듣기 때문에 영원히 Connection refused가 된다. (Global Constraints)
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:8123/ping || exit 1"]
      interval: 2s
      timeout: 3s
      retries: 30
```

`infra/README.md`:

```markdown
# infra

## 로컬 의존성 기동

    docker compose --env-file infra/envs/example/compose.env \
      -f infra/docker-compose/postgres.yml \
      -f infra/docker-compose/clickhouse.yml \
      up -d

Postgres는 상태(키·가드레일 정의·승인), ClickHouse는 감사 이벤트를 담는다.
접근 패턴에 따른 분리이며 근거는 §10에 있다.

`--env-file`은 필수다. 빼면 `cpus`가 빈 문자열이 되어
`strconv.ParseFloat: parsing "": invalid syntax`로 죽는다. 프로젝트 이름은
`compose.env`의 `COMPOSE_PROJECT_NAME`이 고정하므로 `-p`는 필요 없다.

서비스별로 파일을 나눠둔 이유는 필요한 것만 조합해 띄울 수 있게 하기 위함이다.
`shared_kernel` 테스트는 DB를 필요로 하지 않으므로 아무것도 띄우지 않고 돈다.

## 포트

이 머신은 다른 스택들이 이미 돌고 있어 기본 포트를 쓰지 않는다.
gardevoir는 21000 블록을 쓰고, 실제 값은 `envs/<dir>/compose.env`에 있다.

    21000  gateway HTTP      21010  PostgreSQL
    21050  console           21020  ClickHouse HTTP

## 자원 상한

컨테이너마다 `mem_limit` / `memswap_limit` / `cpus`를 건다.
`memswap_limit`을 `mem_limit`과 같게 두면 컨테이너가 예산을 넘어 스왑하지 못한다.
```

- [ ] **Step 5: 동기 확인**

```bash
cd backend && uv sync --all-packages
uv run python -c "import shared_kernel; print(shared_kernel.__version__)"
```

Expected: `0.1.0`

> ⚠️ **`--all-packages`가 필수다.** 가상 워크스페이스 루트(`package = false`)는 설치할
> 프로젝트가 없어서 맨 `uv sync`는 **아무것도 설치하지 않는다**(`Checked in 0.00ms`).
> 그리고 실패 양상이 원인을 가리지 않는다 — 설치가 안 된 상태에서도
> `import shared_kernel`이 **성공한다.** `backend/`가 cwd이면 `backend/shared_kernel/`
> 디렉토리가 암묵적 namespace package로 잡혀 속이 빈 모듈이 임포트되고,
> `AttributeError: module 'shared_kernel' has no attribute '__version__'`로 나타난다.
>
> BC 디렉토리에서 작업할 때는 그 멤버가 `shared-kernel`을 의존성으로 선언하고 있으므로
> `uv sync`만으로도 들어온다. 루트에서 전체를 세울 때만 `--all-packages`가 필요하다.

- [ ] **Step 6: 두 DB 기동 확인**

```bash
docker compose --env-file infra/envs/example/compose.env \
  -f infra/docker-compose/postgres.yml \
  -f infra/docker-compose/clickhouse.yml up -d
```

헬스 판정은 `docker inspect`로 한다 — `grep healthy`는 `unhealthy`도 매치한다.

```bash
for i in $(seq 1 60); do
  pg=$(docker inspect gardevoir-postgres-1 --format '{{.State.Health.Status}}' 2>/dev/null)
  ch=$(docker inspect gardevoir-clickhouse-1 --format '{{.State.Health.Status}}' 2>/dev/null)
  [ "$pg" = "healthy" ] && [ "$ch" = "healthy" ] && { echo "both healthy (${i}s)"; break; }
  sleep 1
done
```

Expected: 60초 이내에 `both healthy`. 실측으로는 ClickHouse가 3초, Postgres가 즉시다.
`ch`가 계속 `unhealthy`면 헬스체크의 호스트가 `127.0.0.1`인지 확인할 것.

```bash
curl -s -u gardevoir:gardevoir "http://localhost:21020/?query=SELECT+version()"
psql "postgresql://gardevoir:gardevoir@localhost:21010/gardevoir" -tAc 'select version()' 2>/dev/null \
  || docker exec gardevoir-postgres-1 psql -U gardevoir -tAc 'select version()'
```

Expected: `25.8.x` / `PostgreSQL 17.x`

- [ ] **Step 7: 자원 사용 확인**

```bash
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' \
  gardevoir-clickhouse-1 gardevoir-postgres-1
```

Expected: ClickHouse가 상한의 25% 미만, Postgres가 10% 미만. 상한에 근접하면
`compose.env`의 값을 올릴 것 — 이 머신은 vLLM 2개가 89Gi를 쓰고 있어 여유가 31Gi다.

- [ ] **Step 8: 커밋**

```bash
git add backend infra
git commit -m "feat: uv 워크스페이스와 로컬 의존성 구성

backend/를 가상 워크스페이스 루트로 두고 shared_kernel을 첫 멤버로 만든다.
infra/docker-compose는 서비스별로 파일을 나누고 포트·자원 상한은
envs/<dir>/compose.env에서만 정한다.

이 머신은 다른 스택이 이미 돌고 있어 21000 블록을 쓴다.
ClickHouse 헬스체크는 127.0.0.1을 쓴다 — localhost는 ::1로 먼저 해석되고
ClickHouse는 IPv4만 들어서 영원히 실패한다."
```

---

## Task 2: shared_kernel — 설정

**Files:**
- Create: `backend/shared_kernel/shared_kernel/config/__init__.py`
- Create: `backend/shared_kernel/shared_kernel/config/settings.py`
- Test: `backend/shared_kernel/tests/test_config.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `DatabaseSettings` — `dsn: str`, `echo: bool = False`
  - `ClickHouseSettings` — `host: str`, `port: int`, `user: str`, `password: str`, `database: str`
  - `LogSettings` — `level: str = "INFO"`, `json_output: bool = True`
  - `BaseAppSettings(BaseSettings)` — `app_name: str`, `debug: bool = False`, `database: DatabaseSettings`, `clickhouse: ClickHouseSettings`, `log: LogSettings`. 중첩 구분자는 `__`.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/shared_kernel/tests/test_config.py`:

```python
import os

import pytest
from pydantic import ValidationError

from shared_kernel.config import BaseAppSettings, ClickHouseSettings, DatabaseSettings, LogSettings


class AppSettings(BaseAppSettings):
    """A BC subclasses BaseAppSettings and adds its own fields."""

    upstream_timeout_s: float = 120.0


def _env(monkeypatch, **extra):
    """Give the test a clean, hermetic environment.

    개발자 셸의 GARDEVOIR_* 변수나 패키지에 놓인 .env 파일이 남아 있으면
    기본값 단정이 조용히 깨진다. 두 경로를 모두 차단한다.
    """
    for name in [k for k in os.environ if k.startswith("GARDEVOIR_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GARDEVOIR_APP_NAME", "gateway")
    monkeypatch.setenv("GARDEVOIR_DATABASE__DSN", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("GARDEVOIR_CLICKHOUSE__HOST", "ch.local")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def _settings(**kwargs) -> AppSettings:
    """Build settings without reading any .env file from the working directory."""
    return AppSettings(_env_file=None, **kwargs)


def test_nested_settings_use_double_underscore(monkeypatch):
    _env(monkeypatch)
    s = _settings()
    assert s.app_name == "gateway"
    assert s.database.dsn == "postgresql+psycopg://u:p@h:5432/d"
    assert s.clickhouse.host == "ch.local"


def test_defaults(monkeypatch):
    _env(monkeypatch)
    s = _settings()
    assert s.debug is False
    assert s.database.echo is False
    assert s.clickhouse.port == 8123
    assert s.clickhouse.user == "gardevoir"
    assert s.clickhouse.database == "gardevoir"
    assert s.log.level == "INFO"
    assert s.log.json_output is True
    assert s.upstream_timeout_s == 120.0


def test_subclass_field_reads_prefixed_env(monkeypatch):
    _env(monkeypatch, GARDEVOIR_UPSTREAM_TIMEOUT_S="7.5")
    assert _settings().upstream_timeout_s == 7.5


def test_missing_required_dsn_fails_loudly(monkeypatch):
    monkeypatch.delenv("GARDEVOIR_DATABASE__DSN", raising=False)
    monkeypatch.setenv("GARDEVOIR_APP_NAME", "gateway")
    with pytest.raises(ValidationError):
        _settings()


def test_unknown_env_is_ignored(monkeypatch):
    _env(monkeypatch, GARDEVOIR_TOTALLY_UNKNOWN="x")
    _settings()  # 예외가 나면 실패


def test_nested_models_are_usable_standalone():
    db = DatabaseSettings(dsn="postgresql+psycopg://u:p@h:5432/d")
    ch = ClickHouseSettings(host="h")
    log = LogSettings()
    assert db.echo is False
    assert ch.port == 8123
    assert log.level == "INFO"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/shared_kernel && uv run pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'shared_kernel.config'`

- [ ] **Step 3: `config/settings.py` 구현**

```python
"""Application settings shared by every bounded context.

A BC subclasses ``BaseAppSettings`` and adds its own fields. Nested settings are
addressed with a double underscore, so the DSN comes from
``GARDEVOIR_DATABASE__DSN``.
"""

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    dsn: str
    echo: bool = False


class ClickHouseSettings(BaseModel):
    host: str = "localhost"
    port: int = 8123
    user: str = "gardevoir"
    password: str = "gardevoir"
    database: str = "gardevoir"


class LogSettings(BaseModel):
    level: str = "INFO"
    json_output: bool = True


class BaseAppSettings(BaseSettings):
    app_name: str
    debug: bool = False

    database: DatabaseSettings
    clickhouse: ClickHouseSettings = ClickHouseSettings()
    log: LogSettings = LogSettings()

    model_config = SettingsConfigDict(
        env_prefix="GARDEVOIR_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )
```

`config/__init__.py`:

```python
from shared_kernel.config.settings import (
    BaseAppSettings,
    ClickHouseSettings,
    DatabaseSettings,
    LogSettings,
)

__all__ = ["BaseAppSettings", "ClickHouseSettings", "DatabaseSettings", "LogSettings"]
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd backend/shared_kernel && uv run pytest tests/test_config.py -v && uv run ruff check && uv run ruff format --check
```

Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/shared_kernel
git commit -m "feat: shared_kernel 설정 계층

BaseAppSettings를 BC가 상속해 자기 필드를 더한다.
중첩 설정은 이중 밑줄로 주소를 잡는다 (GARDEVOIR_DATABASE__DSN)."
```

---

## Task 3: shared_kernel — 예외

애그리거트당 `ErrorCatalog` enum 하나로 에러를 정의하고, 클래스당 에러를 만들지 않는다. BC는 enum에 한 줄을 더한다.

**Files:**
- Create: `backend/shared_kernel/shared_kernel/exception/__init__.py`
- Create: `backend/shared_kernel/shared_kernel/exception/base.py`
- Create: `backend/shared_kernel/shared_kernel/exception/catalog.py`
- Create: `backend/shared_kernel/shared_kernel/exception/schema.py`
- Test: `backend/shared_kernel/tests/test_exception.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `ErrorCode(StrEnum)` — `INTERNAL`, `VALIDATION`, `NOT_FOUND`, `UNAUTHORIZED`, `FORBIDDEN`, `CONFLICT`
  - `AppError(Exception)` — `code`, `http_status`, `log_level`; `__init__(message=None, *, code=None, details=None)`
  - 카테고리: `ValidationError(422)`, `NotFoundError(404)`, `UnauthorizedError(401)`, `ForbiddenError(403)`, `ConflictError(409)`
  - `ErrorCatalog(Enum)` — 멤버 값 `(code, default_message, category)`; `.exception(message=None, *, details=None) -> AppError`, `.raise_(...) -> NoReturn`
  - `ErrorResponse` — `code: str`, `message: str`, `details: dict | None`, `request_id: str | None`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/shared_kernel/tests/test_exception.py`:

```python
import logging

import pytest

from shared_kernel.exception import (
    AppError,
    ConflictError,
    ErrorCatalog,
    ErrorCode,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


class ApiKeyError(ErrorCatalog):
    """A BC's catalog: one line per error, no class per error."""

    INVALID_KEY = ("APIKEY-001", "the provided API key is not valid", UnauthorizedError)
    GUARDRAIL_NOT_ALLOWED = ("APIKEY-002", "guardrail not allowed for this key", ForbiddenError)
    DUPLICATE_NAME = ("APIKEY-003", "an API key with this name already exists", ConflictError)


def test_category_defaults():
    assert ValidationError().http_status == 422
    assert NotFoundError().http_status == 404
    assert UnauthorizedError().http_status == 401
    assert ForbiddenError().http_status == 403
    assert ConflictError().http_status == 409
    assert AppError().http_status == 500
    assert AppError().code is ErrorCode.INTERNAL


def test_client_errors_log_at_warning_not_error():
    """4xx는 우리 잘못이 아니다. ERROR로 남기면 알람이 무의미해진다."""
    assert ValidationError().log_level == logging.WARNING
    assert NotFoundError().log_level == logging.WARNING
    assert UnauthorizedError().log_level == logging.WARNING
    assert ForbiddenError().log_level == logging.WARNING
    assert ConflictError().log_level == logging.WARNING
    assert AppError().log_level == logging.ERROR


def test_catalog_member_builds_its_error():
    exc = ApiKeyError.INVALID_KEY.exception()
    assert isinstance(exc, UnauthorizedError)
    assert exc.code == "APIKEY-001"
    assert exc.message == "the provided API key is not valid"
    assert exc.http_status == 401
    assert exc.details is None


def test_catalog_member_accepts_override_and_details():
    exc = ApiKeyError.GUARDRAIL_NOT_ALLOWED.exception(
        "guardrail 'x' is not allowed", details={"requested": "x", "allowed": ["base"]}
    )
    assert isinstance(exc, ForbiddenError)
    assert exc.message == "guardrail 'x' is not allowed"
    assert exc.details == {"requested": "x", "allowed": ["base"]}


def test_catalog_raise_helper():
    with pytest.raises(ConflictError) as info:
        ApiKeyError.DUPLICATE_NAME.raise_()
    assert info.value.code == "APIKEY-003"


def test_catalog_exposes_code_and_category():
    assert ApiKeyError.INVALID_KEY.code == "APIKEY-001"
    assert ApiKeyError.INVALID_KEY.category is UnauthorizedError
    assert ApiKeyError.INVALID_KEY.default_message


def test_error_response_serialises_camel_case():
    body = ErrorResponse(
        code="APIKEY-001", message="nope", details={"a": 1}, request_id="req_1"
    ).model_dump(by_alias=True)
    assert body == {
        "code": "APIKEY-001",
        "message": "nope",
        "details": {"a": 1},
        "requestId": "req_1",
    }


def test_error_response_omits_absent_optional_fields():
    body = ErrorResponse(code="X", message="m").model_dump(by_alias=True, exclude_none=True)
    assert body == {"code": "X", "message": "m"}
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/shared_kernel && uv run pytest tests/test_exception.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'shared_kernel.exception'`

- [ ] **Step 3: `exception/base.py` 구현**

```python
"""Error categories.

An error's category decides its HTTP status and log level. A bounded context
never subclasses these — it adds a line to its ``ErrorCatalog`` instead.
"""

import logging
from enum import StrEnum


class ErrorCode(StrEnum):
    INTERNAL = "INTERNAL"
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"


class AppError(Exception):
    code: object = ErrorCode.INTERNAL
    http_status: int = 500
    log_level: int = logging.ERROR

    def __init__(
        self,
        message: str | None = None,
        *,
        code: object | None = None,
        details: dict | None = None,
    ) -> None:
        if code is not None:
            self.code = code  # BC-scoped string, set by ErrorCatalog
        self.message = message or self.__class__.__name__
        self.details = details
        super().__init__(self.message)


class ValidationError(AppError):
    code = ErrorCode.VALIDATION
    http_status = 422
    log_level = logging.WARNING


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    http_status = 404
    log_level = logging.WARNING


class UnauthorizedError(AppError):
    code = ErrorCode.UNAUTHORIZED
    http_status = 401
    log_level = logging.WARNING


class ForbiddenError(AppError):
    code = ErrorCode.FORBIDDEN
    http_status = 403
    log_level = logging.WARNING


class ConflictError(AppError):
    code = ErrorCode.CONFLICT
    http_status = 409
    log_level = logging.WARNING
```

- [ ] **Step 4: `exception/catalog.py` 구현**

```python
"""Per-aggregate error catalog.

Each member's value is ``(code, default_message, category)``. The member acts as
the factory for its error, so a bounded context adds one enum line per error and
never writes a class per error.
"""

from enum import Enum
from typing import NoReturn

from shared_kernel.exception.base import AppError


class ErrorCatalog(Enum):
    def __init__(self, code: str, default_message: str, category: type[AppError]) -> None:
        self.code = code
        self.default_message = default_message
        self.category = category

    def exception(self, message: str | None = None, *, details: dict | None = None) -> AppError:
        return self.category(message or self.default_message, code=self.code, details=details)

    def raise_(self, message: str | None = None, *, details: dict | None = None) -> NoReturn:
        raise self.exception(message, details=details)
```

- [ ] **Step 5: `exception/schema.py` 구현**

`CamelModel`은 Task 4에서 만든다. 순환을 피하려고 여기서는 `pydantic`을 직접 쓰고, Task 4에서 `CamelModel` 상속으로 바꾼다.

```python
"""Error response body."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ErrorResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code: str
    message: str
    details: dict | None = None
    request_id: str | None = None
```

`exception/__init__.py`:

```python
from shared_kernel.exception.base import (
    AppError,
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from shared_kernel.exception.catalog import ErrorCatalog
from shared_kernel.exception.schema import ErrorResponse

__all__ = [
    "AppError",
    "ConflictError",
    "ErrorCatalog",
    "ErrorCode",
    "ErrorResponse",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "ValidationError",
]
```

- [ ] **Step 6: 테스트 통과 확인**

```bash
cd backend/shared_kernel && uv run pytest tests/test_exception.py -v && uv run ruff check && uv run ruff format --check
```

Expected: 8 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/shared_kernel
git commit -m "feat: shared_kernel 예외 계층

카테고리가 HTTP 상태와 로그 레벨을 결정하고, BC는 ErrorCatalog enum에
한 줄을 더한다. 클래스당 에러를 만들지 않는다.

4xx는 WARNING으로 남긴다 — 우리 잘못이 아닌 것을 ERROR로 남기면
알람이 무의미해진다."
```

---

## Task 4: shared_kernel — API 스키마 + 예외 핸들러

**Files:**
- Create: `backend/shared_kernel/shared_kernel/api/__init__.py`
- Create: `backend/shared_kernel/shared_kernel/api/schema.py`
- Create: `backend/shared_kernel/shared_kernel/exception/handlers.py`
- Modify: `backend/shared_kernel/shared_kernel/exception/schema.py`
- Modify: `backend/shared_kernel/shared_kernel/exception/__init__.py`
- Test: `backend/shared_kernel/tests/test_api_schema.py`
- Test: `backend/shared_kernel/tests/test_handlers.py`

**Interfaces:**
- Consumes: Task 3의 `AppError`, `ErrorResponse`
- Produces:
  - `shared_kernel.api.CamelModel(BaseModel)` — camelCase 와이어 / snake_case 파이썬
  - `shared_kernel.api.Page[T]` — `items: list[T]`, `total: int`
  - `shared_kernel.exception.register_exception_handlers(app: FastAPI) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/shared_kernel/tests/test_api_schema.py`:

```python
from shared_kernel.api import CamelModel, Page


class GuardrailSummary(CamelModel):
    guardrail_name: str
    guardrail_version: int


def test_serialises_to_camel_case():
    dto = GuardrailSummary(guardrail_name="doc-agent", guardrail_version=37)
    assert dto.model_dump(by_alias=True) == {
        "guardrailName": "doc-agent",
        "guardrailVersion": 37,
    }


def test_accepts_both_camel_and_snake_on_input():
    assert GuardrailSummary(guardrailName="a", guardrailVersion=1).guardrail_name == "a"
    assert GuardrailSummary(guardrail_name="b", guardrail_version=2).guardrail_name == "b"


def test_page_is_generic():
    page = Page[GuardrailSummary](
        items=[GuardrailSummary(guardrail_name="a", guardrail_version=1)], total=42
    )
    body = page.model_dump(by_alias=True)
    assert body["total"] == 42
    assert body["items"][0]["guardrailName"] == "a"
```

`backend/shared_kernel/tests/test_handlers.py`:

```python
import httpx
import pytest
from fastapi import FastAPI

from shared_kernel.exception import (
    AppError,
    ErrorCatalog,
    NotFoundError,
    UnauthorizedError,
    register_exception_handlers,
)


class ThingError(ErrorCatalog):
    MISSING = ("THING-001", "no such thing", NotFoundError)
    NO_KEY = ("THING-002", "key required", UnauthorizedError)


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/missing")
    async def missing():
        ThingError.MISSING.raise_()

    @app.get("/detailed")
    async def detailed():
        ThingError.NO_KEY.raise_(details={"header": "authorization"})

    @app.get("/boom")
    async def boom():
        raise AppError("something broke internally")

    @app.get("/unhandled")
    async def unhandled():
        raise RuntimeError("not an AppError")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_catalog_error_maps_to_its_category_status(client):
    async with client as c:
        r = await c.get("/missing")
    assert r.status_code == 404
    assert r.json() == {"code": "THING-001", "message": "no such thing"}


async def test_details_are_included_when_present(client):
    async with client as c:
        r = await c.get("/detailed")
    assert r.status_code == 401
    assert r.json()["details"] == {"header": "authorization"}


async def test_internal_apperror_is_500_with_generic_code(client):
    async with client as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL"


async def test_unexpected_exception_does_not_leak_its_message(client):
    """예상 못 한 예외의 메시지는 내부 정보다. 클라이언트에 흘리지 않는다."""
    async with client as c:
        r = await c.get("/unhandled")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL"
    assert "not an AppError" not in r.text
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/shared_kernel && uv run pytest tests/test_api_schema.py tests/test_handlers.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'shared_kernel.api'`

- [ ] **Step 3: `api/schema.py` 구현**

```python
"""Wire DTO base.

camelCase on the wire, snake_case in Python. Applies to DTOs that cross the HTTP
boundary.

It must NOT be used for types on the request evaluation path — Pydantic
validation there would cost more than the entire per-request guardrail budget
of 0.63 ms (§11.8).
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Page[T](CamelModel):
    items: list[T]
    total: int
```

`api/__init__.py`:

```python
from shared_kernel.api.schema import CamelModel, Page

__all__ = ["CamelModel", "Page"]
```

- [ ] **Step 4: `ErrorResponse`를 `CamelModel` 상속으로 교체**

`exception/schema.py` 전체를 교체:

```python
"""Error response body."""

from shared_kernel.api.schema import CamelModel


class ErrorResponse(CamelModel):
    code: str
    message: str
    details: dict | None = None
    request_id: str | None = None
```

- [ ] **Step 5: `exception/handlers.py` 구현**

```python
"""Central exception handling. One implementation for every bounded context.

Never register a per-BC handler — the response shape is part of the contract.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse

from shared_kernel.exception.base import AppError, ErrorCode
from shared_kernel.exception.schema import ErrorResponse

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> ORJSONResponse:
        logger.log(
            exc.log_level,
            "%s %s -> %s %s",
            request.method,
            request.url.path,
            exc.code,
            exc.message,
        )
        body = ErrorResponse(code=str(exc.code), message=exc.message, details=exc.details)
        return ORJSONResponse(
            body.model_dump(by_alias=True, exclude_none=True),
            status_code=exc.http_status,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> ORJSONResponse:
        # 예상 못 한 예외의 메시지는 내부 정보다. 로그에는 남기고 응답에는 싣지 않는다.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        body = ErrorResponse(code=str(ErrorCode.INTERNAL), message="internal server error")
        return ORJSONResponse(body.model_dump(by_alias=True, exclude_none=True), status_code=500)
```

`exception/__init__.py`에 추가:

```python
from shared_kernel.exception.handlers import register_exception_handlers
```

그리고 `__all__`에 `"register_exception_handlers"`를 더한다.

- [ ] **Step 6: 테스트 통과 확인**

```bash
cd backend/shared_kernel && uv run pytest -v && uv run ruff check && uv run ruff format --check
```

Expected: 21 passed (config 6 + exception 8 + api 3 + handlers 4)

- [ ] **Step 7: 커밋**

```bash
git add backend/shared_kernel
git commit -m "feat: shared_kernel API 스키마와 중앙 예외 핸들러

CamelModel은 HTTP 경계를 건너는 DTO에만 쓴다 — 요청 판정 경로에
Pydantic 검증이 들어가면 가드레일 예산 전체보다 비싸진다.

예상 못 한 예외의 메시지는 응답에 싣지 않는다. 내부 정보다."
```

---

## Task 5: shared_kernel — 데이터베이스 베이스 + 로깅

**Files:**
- Create: `backend/shared_kernel/shared_kernel/database/__init__.py`
- Create: `backend/shared_kernel/shared_kernel/database/base.py`
- Create: `backend/shared_kernel/shared_kernel/log/__init__.py`
- Create: `backend/shared_kernel/shared_kernel/log/context.py`
- Create: `backend/shared_kernel/shared_kernel/log/middleware.py`
- Create: `backend/shared_kernel/shared_kernel/log/setup.py`
- Test: `backend/shared_kernel/tests/test_database.py`
- Test: `backend/shared_kernel/tests/test_log.py`

**Interfaces:**
- Consumes: Task 2의 `LogSettings`
- Produces:
  - `shared_kernel.database.Base` — `DeclarativeBase` + `naming_convention`
  - `shared_kernel.database.TimestampMixin` — `created_at`, `updated_at` (tz-aware, server default)
  - `shared_kernel.log.get_request_id() -> str | None`
  - `shared_kernel.log.set_request_id(value: str) -> None`
  - `shared_kernel.log.RequestContextMiddleware` — ASGI 미들웨어, `X-Request-Id`를 읽거나 생성해 컨텍스트에 넣고 응답에 되돌려준다
  - `shared_kernel.log.configure_logging(settings: LogSettings) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/shared_kernel/tests/test_database.py`:

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from shared_kernel.database import Base, TimestampMixin


class Widget(Base, TimestampMixin):
    __tablename__ = "widgets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


def test_naming_convention_gives_deterministic_constraint_names():
    """Alembic autogenerate가 안정적인 이름을 내야 마이그레이션 diff가 조용해진다."""
    names = {c.name for c in Widget.__table__.constraints if c.name}
    assert "pk_widgets" in names
    indexes = {i.name for i in Widget.__table__.indexes}
    unique = {c.name for c in Widget.__table__.constraints if c.name and c.name.startswith("uq_")}
    assert indexes or unique


def test_timestamp_mixin_adds_both_columns():
    cols = Widget.__table__.c
    assert "created_at" in cols
    assert "updated_at" in cols
    assert cols["created_at"].type.timezone is True
    assert cols["created_at"].server_default is not None
```

`backend/shared_kernel/tests/test_log.py`:

```python
import httpx
import pytest
from fastapi import FastAPI

from shared_kernel.config import LogSettings
from shared_kernel.log import (
    RequestContextMiddleware,
    configure_logging,
    get_request_id,
    set_request_id,
)


def test_request_id_context_roundtrip():
    set_request_id("req_abc")
    assert get_request_id() == "req_abc"


@pytest.fixture
def app():
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)

    @application.get("/who")
    async def who():
        return {"request_id": get_request_id()}

    return application


async def test_middleware_reuses_incoming_request_id(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/who", headers={"x-request-id": "req_from_caller"})
    assert r.json()["request_id"] == "req_from_caller"
    assert r.headers["x-request-id"] == "req_from_caller"


async def test_middleware_generates_one_when_absent(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/who")
    generated = r.json()["request_id"]
    assert generated
    assert r.headers["x-request-id"] == generated


async def test_request_ids_are_not_shared_between_requests(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        first = (await c.get("/who")).json()["request_id"]
        second = (await c.get("/who")).json()["request_id"]
    assert first != second


def test_configure_logging_is_idempotent():
    configure_logging(LogSettings(level="DEBUG", json_output=True))
    configure_logging(LogSettings(level="DEBUG", json_output=True))
    import logging

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd backend/shared_kernel && uv run pytest tests/test_database.py tests/test_log.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'shared_kernel.database'`

- [ ] **Step 3: `database/base.py` 구현**

```python
"""Declarative base and common column mixins.

The naming convention matters for Alembic: without it, autogenerate produces
database-assigned constraint names and every diff becomes noisy.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

`database/__init__.py`:

```python
from shared_kernel.database.base import NAMING_CONVENTION, Base, TimestampMixin

__all__ = ["NAMING_CONVENTION", "Base", "TimestampMixin"]
```

- [ ] **Step 4: `log/context.py`와 `log/middleware.py` 구현**

`log/context.py`:

```python
"""Request-scoped correlation id.

A ContextVar is used so the id follows the request across awaits without being
threaded through every call signature.
"""

from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_HEADER = "X-Request-Id"


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str) -> None:
    _request_id.set(value)
```

`log/middleware.py`:

```python
"""Correlation id middleware.

Reuses the caller's X-Request-Id when present so gateway audit rows can be
joined against the caller's own logs (§7.2), and echoes it back.
"""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from shared_kernel.log.context import REQUEST_ID_HEADER, set_request_id


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        set_request_id(request_id)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
```

- [ ] **Step 5: `log/setup.py` 구현**

```python
"""Logging configuration.

Idempotent: calling it twice must not double every log line. Tests and reload
paths call it more than once.
"""

import logging
import sys

import orjson

from shared_kernel.config.settings import LogSettings
from shared_kernel.log.context import get_request_id


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return orjson.dumps(payload).decode()


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = get_request_id() or "-"
        return f"{record.levelname:<8} [{rid}] {record.name}: {record.getMessage()}"


def configure_logging(settings: LogSettings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if settings.json_output else _TextFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.level.upper())
```

`log/__init__.py`:

```python
from shared_kernel.log.context import REQUEST_ID_HEADER, get_request_id, set_request_id
from shared_kernel.log.middleware import RequestContextMiddleware
from shared_kernel.log.setup import configure_logging

__all__ = [
    "REQUEST_ID_HEADER",
    "RequestContextMiddleware",
    "configure_logging",
    "get_request_id",
    "set_request_id",
]
```

- [ ] **Step 6: 전체 테스트 통과 확인**

```bash
cd backend/shared_kernel && uv run pytest -v && uv run ruff check && uv run ruff format --check
```

Expected: 28 passed (config 6 + exception 8 + api 3 + handlers 4 + database 2 + log 5)

- [ ] **Step 7: 커밋**

```bash
git add backend/shared_kernel
git commit -m "feat: shared_kernel 데이터베이스 베이스와 로깅

naming_convention은 Alembic autogenerate가 안정적인 제약 이름을 내게 해서
마이그레이션 diff를 조용하게 유지한다.

RequestContextMiddleware는 호출자의 X-Request-Id를 재사용한다 — 감사 로그를
호출자 로그와 이어붙일 수 있어야 한다. configure_logging은 멱등이다."
```

---

## Self-Review

**1. Spec coverage (Phase 1a 범위)**

| 요구사항 | 태스크 |
|---|---|
| uv 워크스페이스 (clic 방식) | Task 1 |
| infra docker-compose 서비스별 분리 | Task 1 |
| `BaseAppSettings` + 중첩 설정 | Task 2 |
| `AppError` + 카테고리 (§gardevoir-be) | Task 3 |
| `ErrorCatalog` (클래스당 에러 금지) | Task 3 |
| `CamelModel` (경계 전용) | Task 4 |
| `register_exception_handlers` (BC별 핸들러 금지) | Task 4 |
| `Base` + naming_convention | Task 5 |
| `X-Request-Id` 상관 (§7.2) | Task 5 |

**Phase 1a 범위 밖:** gateway BC 전체(Phase 1b), 가드레일 컴파일(Phase 2), 액션 통제(Phase 3), 모델 티어(Phase 4), UI(Phase 5), 승인(Phase 6).

**2. Placeholder scan**

TBD/TODO 없음. 모든 코드 스텝에 실제 코드가 있다.

한 가지 순서 의존이 있다: `ErrorResponse`가 Task 3에서 `pydantic.BaseModel`로 만들어지고 Task 4에서 `CamelModel` 상속으로 교체된다. `api`가 `exception`을 임포트하지 않으므로 순환은 없고, Task 3만 완료한 상태에서도 테스트가 통과한다. Task 4 Step 4에 교체를 명시했다.

**3. Type consistency**

- `AppError.code`를 `object`로 타이핑했다. 카테고리 클래스는 `ErrorCode`(StrEnum)를 기본값으로 두고, `ErrorCatalog`가 BC 문자열(`"APIKEY-001"`)로 인스턴스 오버라이드한다. 핸들러가 `str(exc.code)`로 정규화하므로 두 경우 모두 같은 응답이 나온다.
- `configure_logging(settings: LogSettings)` — Task 2의 `LogSettings`를 받는다. `BaseAppSettings.log`가 그 타입이다.
- `REQUEST_ID_HEADER`는 `log/context.py`가 소유하고 미들웨어가 임포트한다. gateway BC의 `contract.py`도 같은 값을 쓰지만 **계약 상수는 gateway가 자기 것으로 다시 선언한다** — `shared_kernel`이 와이어 계약을 소유하면 계약 변경이 모든 BC를 흔든다.
- `Page[T]`는 `CamelModel`을 상속하므로 중첩 DTO도 camelCase로 직렬화된다.

---

## 실행 후 기록

Phase 1a는 완료됐다. 테스트 50개 / ruff 통과 / clean venv 재현 확인.
실행이 드러낸 것들은 위 본문에 반영했고, 아래는 **Phase 1b로 넘긴 항목**이다.

### Phase 1b가 처리할 것

**`HTTPException` / `RequestValidationError`가 중앙 핸들러를 우회한다.**
`register_exception_handlers`는 `AppError`와 `Exception`만 등록한다. FastAPI가 자체
처리하는 422(요청 검증)와 `HTTPException`은 `ErrorResponse` 형태가 아닌 몸통으로
나간다. Phase 1a에는 실제 엔드포인트가 없어 관측되지 않았다. BC가 라우터를 붙일 때
`shared_kernel`에 두 핸들러를 추가한다 — 422는 `ValidationError` 카테고리 코드로,
`exc.errors()`에서 `input`/`url`을 제거하고 `loc`+`msg`만 `details`에 넣는다.

**미처리 예외 500 응답에 `X-Request-Id`가 붙지 않는다.**
`Exception` 핸들러는 `RequestContextMiddleware` 바깥의 `ServerErrorMiddleware`에서
실행되기 때문이다. `AppError` 경로(4xx·5xx)와 정상 응답에는 모두 붙는다. 감사 행의
`request_id`는 ContextVar에서 오므로 §7.2의 목적(앱↔감사 로그 상관)은 깨지지 않고,
잔여 영향은 "자기 id를 안 보낸 호출자가 크래시 응답에서 생성된 id를 볼 수 없다"뿐이다.
Phase 1b에서 앱을 조립할 때 **미들웨어와 핸들러를 함께 등록한 통합 테스트**와 함께
처리한다 — 지금 그 테스트가 없다는 것이 회귀 미검출의 실체다.

### 다음 계획서를 쓸 때 이어받을 교훈

- 상수·속성 값만 단정하는 테스트는 그 값을 소비하는 배선을 검증하지 않는다.
  Phase 1a에서 `logger.log` 전체를 지워도 테스트 36개가 통과했다. 계획서에 테스트를
  쓸 때 **"이 코드를 지우면 어느 테스트가 실패하는가"** 를 자문할 것.
- 픅스처가 주변 환경(셸 변수, `.env`)을 차단하지 않으면 개발자 기계에서만 깨진다.
  BC 설정 테스트도 같은 `_env` + `_env_file=None` 형태를 쓸 것.
- 돌연변이 테스트 전에 커밋할 것. `git checkout --`로 원복하면 커밋하지 않은 수정도
  함께 사라진다.

Phase 1b(gateway BC)는 별도 계획서로 작성한다.
