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

## ⚠️ Admin API 노출 금지 (Phase 5 까지)

`/v1/admin/*` 은 아직 **사람 인증이 없다.** `admin` 스코프를 가진 API 키만 요구하므로,
그 키가 새면 가드레일 정책 전체를 바꿀 수 있다 — 즉 프록시 검사를 무력화할 수 있다.

Phase 5(콘솔)가 관리자 인증(세션/OIDC)을 정할 때까지:

- `/v1/admin/*` 을 리버스 프록시/인그레스에서 차단하거나, gateway 를 사설망에만 노출한다.
- `admin` 스코프 키는 운영자 로컬에서만 쓰고 애플리케이션에 배포하지 않는다.
- 프록시용 키에는 `admin` 을 주지 않는다 (기본값은 `proxy` 뿐이다).

```bash
# 프록시 키 (기본)
uv run gardevoir-createkey --name my-app --upstream-base-url https://api.openai.com/v1 ...

# 관리자 키 — 별도로 만든다
uv run gardevoir-createkey --name ops-console --scope admin ...
```

설계 문서 §14 에 미해결 항목으로 기록돼 있다.

## ⚠️ 테스트 스위트와 개발 서버는 DB 를 공유한다

`backend/gateway/tests/conftest.py` 의 기본 DSN 이 로컬 개발용과 같다. 그래서:

- **`uv run pytest` 가 개발용 데이터를 지운다.** 세션 픽스처가 `drop_all` +
  `create_all` 을 돌리므로 API 키와 가드레일이 사라진다. 수동 확인 중이었다면 키를
  다시 만들어야 한다.
- **개발 서버를 띄운 채로 테스트를 돌리면 스위트가 멈춘다.** 서버가 잡고 있는
  커넥션 때문에 `drop_all` 이 잠금 대기에 걸린다. 증상은 "특정 파일에서 멈춤"이라
  코드 문제처럼 보인다.

수동 확인을 하려면 서버를 내리고 테스트를 돌리거나, 별도 DB 를 쓴다:

```bash
GARDEVOIR_DATABASE__DSN=postgresql+psycopg://gardevoir:gardevoir@localhost:21010/gardevoir_dev \
  uv run uvicorn --factory gateway.presentation.http.app:create_app --port 21000
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
