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
  -p gardevoir up -d
```

Postgres는 상태(키·가드레일 정의·승인), ClickHouse는 감사 이벤트를 담는다.
접근 패턴에 따른 분리이며 근거는 설계 문서 §10에 있다.

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

실측 여유 (설계 문서 §11.10):

```
ClickHouse   426 MiB / 2 GiB   (20.8%)
Postgres      35 MiB / 512 MiB  (6.9%)
```

상한에 근접하면 `compose.env`의 값을 올린다.
