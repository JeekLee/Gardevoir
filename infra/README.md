# infra

## 백엔드 의존성 설치

```bash
cd backend && uv sync --all-packages
```

`--all-packages`가 필수다. 가상 워크스페이스 루트는 설치할 프로젝트가 없어서 맨
`uv sync`는 아무것도 설치하지 않고, 그 상태에서도 `import shared_kernel`이 성공한다
(`backend/`가 cwd일 때 디렉토리가 namespace package로 잡힌다). 속이 빈 모듈이라
`AttributeError`로 드러난다.

## 로컬 의존성 기동

```bash
docker compose --env-file infra/envs/example/compose.env \
  -f infra/docker-compose/postgres.yml \
  -f infra/docker-compose/redis.yml \
  -f infra/docker-compose/clickhouse.yml \
  up -d
```

Postgres는 상태(키·가드레일 정의·승인), ClickHouse는 감사 이벤트를 담는다.
접근 패턴에 따른 분리이며 근거는 §10에 있다.

`--env-file`은 필수다. 빼면 `cpus` 값이 빈 문자열이 되어
`strconv.ParseFloat: parsing "": invalid syntax`로 죽는다. 프로젝트 이름은
`compose.env`의 `COMPOSE_PROJECT_NAME`이 고정하므로 `-p`는 필요 없다.

서비스별로 파일을 나눠둔 이유는 필요한 것만 조합해 띄울 수 있게 하기 위함이다.
`shared_kernel` 테스트는 DB를 필요로 하지 않으므로 아무것도 띄우지 않고 돈다.

## 헬스 확인

`grep healthy`를 쓰지 않는다 — `unhealthy`도 매치된다.

```bash
for i in $(seq 1 60); do
  pg=$(docker inspect gardevoir-postgres-1 --format '{{.State.Health.Status}}' 2>/dev/null)
  ch=$(docker inspect gardevoir-clickhouse-1 --format '{{.State.Health.Status}}' 2>/dev/null)
  [ "$pg" = "healthy" ] && [ "$ch" = "healthy" ] && { echo "both healthy (${i}s)"; break; }
  sleep 1
done
```

ClickHouse가 계속 `unhealthy`면 헬스체크의 호스트가 `127.0.0.1`인지 확인할 것.
`localhost`는 `::1`로 먼저 해석되고 ClickHouse는 IPv4만 들어서 영원히 실패한다.

## 포트

이 머신은 다른 스택이 이미 돌고 있어 기본 포트를 쓰지 않는다.
gardevoir는 21000 블록을 쓰고, 실제 값은 `envs/<dir>/compose.env`에 있다.

```
21000  gateway HTTP      21010  PostgreSQL
21050  console           21020  ClickHouse HTTP
```

## 자원 상한

컨테이너마다 `mem_limit` / `memswap_limit` / `cpus`를 건다.
`memswap_limit`을 `mem_limit`과 같게 두면 컨테이너가 예산을 넘어 스왑하지 못한다.

실측 여유 (§11.10):

```
ClickHouse   426 MiB / 2 GiB   (20.8%)
Postgres      35 MiB / 512 MiB  (6.9%)
```

상한에 근접하면 `compose.env`의 값을 올린다.

## 최초 계정과 로그인

관리 경로는 **관리자 사용자의 액세스 토큰**을 요구한다. 경로에 `admin` 접두어는 없다 —
권한은 자원의 성질이 아니라 호출자의 성질이므로 라우트마다 역할로 붙는다.

최초 계정은 **환경변수로 심는다.** 계정을 만들려면 로그인해야 하고 로그인하려면 계정이
있어야 하므로, 이것이 순환을 끊는 유일한 장치다. **사용자가 하나도 없을 때만** 만들어진다.

```bash
GARDEVOIR_JWT_SECRET=$(openssl rand -hex 32) \
GARDEVOIR_ROOT_EMAIL=ops@example.com \
GARDEVOIR_ROOT_PASSWORD='<12자 이상>' \
  uv run uvicorn --factory gateway.app:create_app --port 21000
```

`GARDEVOIR_JWT_SECRET` 에는 기본값이 없다 — 두면 그 값이 곧 취약점이다. RFC 7518 §3.2 가
HS256 에 요구하는 32바이트 이상이어야 한다.

```bash
# 로그인 — 액세스 15분, 리프레시 14일
curl -X POST localhost:21000/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"ops@example.com","password":"..."}'

A="authorization: Bearer <accessToken>"

# 사용자 생성 (admin 필요). 초기 비밀번호를 함께 준다
curl -H "$A" -X POST localhost:21000/v1/users -H 'content-type: application/json' \
  -d '{"email":"dev@example.com","name":"dev","password":"<12자 이상>"}'

# 갱신 — 리프레시 토큰이 회전한다. 옛 토큰은 그 즉시 무효다
curl -X POST localhost:21000/v1/auth/refresh -H 'content-type: application/json' \
  -d '{"refreshToken":"..."}'

# 로그아웃 — 세션을 없앤다
curl -X POST localhost:21000/v1/auth/logout -H 'content-type: application/json' \
  -d '{"refreshToken":"..."}'
```

세션은 Redis 에 있고 TTL 이 만료를 처리한다. 비밀번호 변경과 계정 비활성화는 그 사용자의
세션을 **전부** 끊는다. 마지막 활성 관리자는 강등·비활성화할 수 없다.

## API 키 (프록시용)

⚠️ **현재 발급 경로가 없다.** identity 의 ApiKey 계층이 재구축 중이다. 복구되면 관리자
토큰으로 발급한다.

키 회수는 즉시 반영될 예정이다 — 키 조회에 캐시가 없고 요청마다 Postgres 를 읽는다
(1.2 ms, 업스트림 300~2000 ms 의 0.4%). 대가로 **Postgres 가 죽으면 프록시가 서지 못한다.**

Postgres와 ClickHouse 스키마는 게이트웨이 기동 전에 각 Alembic lineage로 올린다.

```bash
cd backend/gateway
uv run alembic -n postgres upgrade head
uv run alembic -n clickhouse upgrade head
```

전체 스택의 `migrate` 서비스도 같은 두 명령을 순서대로 실행하며, Postgres와
ClickHouse가 모두 healthy가 된 뒤 시작한다.

설계 문서 §14 에 미해결 항목으로 기록돼 있다.

## ⚠️ 로컬 DB 는 하나다

지금은 테스트 스위트가 없어서(→ AGENTS.md) 개발 서버만 이 DB 를 쓴다. 하지만 DB 를
지우는 도구를 돌릴 때는 여전히 주의해야 한다:

- **`Base.metadata.drop_all` 을 도는 것은 무엇이든 개발용 데이터를 지운다.** API 키와
  가드레일이 사라지므로 수동 확인 중이었다면 다시 만들어야 한다.
- **개발 서버를 띄운 채로 DDL 을 돌리면 잠금 대기에 걸린다.** 서버가 잡고 있는 커넥션
  때문에 `drop_all`·`TRUNCATE` 가 멈춘다. 증상이 "특정 지점에서 멈춤"이라 코드 문제처럼
  보인다.

별도 DB 를 쓰려면:

```bash
GARDEVOIR_DATABASE__DSN=postgresql+psycopg://gardevoir:gardevoir@localhost:21010/gardevoir_dev \
  uv run uvicorn --factory gateway.app:create_app --port 21000
```

멈췄을 때 진단·해제:

```sql
SELECT pid, state, wait_event_type, left(query, 60)
FROM pg_stat_activity WHERE datname = 'gardevoir' AND pid <> pg_backend_pid();
SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity
WHERE datname = 'gardevoir' AND pid <> pg_backend_pid();
```

## 발행 반영 시점

발행은 **응답 전에** 그 워커에 반영된다 (`GuardrailService` 가 커밋과 재컴파일 시점을
직접 갖는다). 다른 워커는 `GARDEVOIR_PLAN_POLL_INTERVAL_S`(기본 5초) 주기로 따라온다.

수동으로 즉시 반영만 확인하려면 폴링 주기를 크게 두고 시험한다 — 그러지 않으면
폴러가 결과를 가려서 즉시 반영이 깨져도 통과한 것처럼 보인다.

```bash
GARDEVOIR_PLAN_POLL_INTERVAL_S=600 uv run uvicorn --factory ... 
```

## 전체 스택 (인프라 + 게이트웨이 + 콘솔)

한 번에 올리기 — 콘솔·게이트웨이 이미지까지 빌드한다:

```bash
docker compose \
  --env-file infra/envs/example/compose.env \
  --env-file infra/envs/local/compose.env \
  -f infra/docker-compose/gardevoir.yml up -d --build
```

- `example/compose.env` 는 템플릿(localhost). 머신별 실제 값은 `infra/envs/local/compose.env`
  에서 덮어쓴다(git 에 커밋하지 않음). 최소 두 가지:
  - `NEXT_PUBLIC_API_BASE` — 브라우저가 호출할 게이트웨이 주소. **next build 때 콘솔 번들로
    고정되므로 바꾸면 `--build` 로 다시 빌드**해야 한다.
  - `GARDEVOIR_CORS_ALLOW_ORIGINS` — 게이트웨이가 허용할 오리진(콘솔을 여는 주소와 일치, 콤마 구분).
- Dockerfile 은 `infra/dockerfiles/`(gateway·console). 콘솔 빌드 컨텍스트는 `frontend/`.

## 모델 티어 (선택)

가드 모델(Shieldstral)은 이 스택이 직접 서빙한다. **`model-tier` 프로필이라 기본 `up` 에서는
뜨지 않는다** — 가중치 15 GB 와 NVIDIA 런타임이 필요하므로 필수로 만들면 빠른 시작이 깨진다.

```bash
docker compose \
  --env-file infra/envs/example/compose.env \
  --env-file infra/envs/local/compose.env \
  -f infra/docker-compose/gardevoir.yml --profile model-tier up -d
```

`local/compose.env` 에 넣을 것:

```
GARDEVOIR_MODEL_JUDGE__ENABLED=true
GARDEVOIR_MODEL_JUDGE__ENDPOINT=http://shieldstral:8001/v1/chat/completions
GARDEVOIR_MODEL_JUDGE__MODEL=shieldstral-1.0-3b       # --served-model-name 과 같은 값
GARDEVOIR_MODEL_JUDGE__REVISION=<snapshot-hash>       # 서빙할 스냅샷이자 감사 식별자
SHIELDSTRAL_MODEL_DIR=/absolute/path/to/models--mistralai--Shieldstral-1.0-3B
```

- `REVISION` 은 감사 식별자이면서 **실제로 서빙하는 스냅샷 경로**다. 한 변수에서 오므로
  감사 로그가 판정한 가중치와 갈릴 수 없다.
- `SHIELDSTRAL_MODEL_DIR` 은 **절대 경로**여야 한다. compose 는 `~` 를 확장하지 않는다.
- 게이트웨이는 이 서비스에 `depends_on` 하지 않는다. 판정 실패는 fail mode 로 처리되는
  정상 경로이고(§4), 의존을 걸면 프로필이 꺼졌을 때 스택이 뜨지 못한다.
- 모델 티어를 끄면(`ENABLED=false`) 프로필 없이 올리면 된다. MODEL 체크는 pending 으로
  통과하고 감사에는 남는다.
