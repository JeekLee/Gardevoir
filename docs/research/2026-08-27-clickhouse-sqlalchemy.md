# SQLAlchemy의 ClickHouse 지원과 gardevoir 적용성 조사

**조사일** 2026-08-27

**대상** gardevoir 감사 조회·쓰기·스키마 경로

**상태** 도입 판단 자료 — 구현 제안이 아님

## 결론

SQLAlchemy는 ClickHouse 방언을 본체에 포함하지 않는다. 외부 방언을 통해서는 사용할 수
있고, 2026-08-27 현재 가장 현실적인 선택지는 gardevoir가 이미 쓰는
[`clickhouse-connect`](https://pypi.org/project/clickhouse-connect/)의 내장
`clickhousedb` 방언이다. 공식 ClickHouse 프로젝트이고 SQLAlchemy 2.x, Core, ClickHouse
타입·테이블 엔진, 제한적인 ORM, Alembic을 지원한다.

그러나 **gardevoir에는 지금 도입하지 않는다.** 현재 read DAO는 세 질의뿐이고 각 질의가
`JSONExtractBool`, `countIf`, `quantileTDigest`, `map` 같은 ClickHouse 문법을 직접 드러낸다.
필터 조립도 아직 작다. SQLAlchemy Core로 옮겨 얻는 조합성보다 새 `Engine`·연결 풀·타입
메타데이터·컴파일 계층의 수명주기가 더 크며, 성능이나 결함 감소 효과도 측정되지 않았다.

도입을 다시 검토할 조건은 감사 대시보드가 늘어 **동적 필터·공통 부분식·재사용 질의의
조합 비용이 raw SQL 유지 비용을 실제로 넘어설 때**다. 그때도 범위는 다음처럼 제한한다.

1. `clickhouse-connect` 내장 방언으로 **read DAO 한 질의만 SQLAlchemy Core 파일럿**한다.
2. ORM은 도입하지 않는다. 감사 이벤트는 append-only 분석 행이지 변경 추적 aggregate가
   아니다.
3. write sink는 `Client.insert()` 배치 경로를 유지한다.
4. ClickHouse 스키마는 번호가 붙은 idempotent `.sql`을 계속 진실의 출처로 둔다.
5. async 전환은 SQLAlchemy 도입과 분리한다. 높은 조회 동시성이 측정되면 우선
   `clickhouse-connect`의 aiohttp 기반 async client를 raw SQL 경로에서 검증한다.

`clickhouse-sqlalchemy` + `asynch`는 실제 `AsyncEngine` 조합을 제공하지만 신규 방언·드라이버,
Native TCP 운영면, 미배포 호환 수정까지 함께 떠안는다. gardevoir의 작은 감사 조회면에는
맞지 않는다. 오래된 `sqlalchemy-clickhouse`는 후보에서 제외한다.

## 조사 기준과 현재 전제

버전·유지보수 상태는 2026-08-27에 PyPI, GitHub, SQLAlchemy와 ClickHouse 공식 문서를
라이브로 확인했다. 별도 패키지를 설치하거나 서버에 후보 구현을 실행하지는 않았다. 따라서
아래에서 “지원”은 upstream 문서와 소스가 선언한 범위이고, gardevoir 조합의 실제 동작과
성능은 마지막 절의 검증 항목으로 분리한다.

현재 저장소 기준은 다음과 같다.

| 항목 | 현재 값 |
|---|---|
| Python | 3.14 |
| SQLAlchemy | 2.0.52 |
| ClickHouse 서버 | 설계·실측 기준 25.8 |
| `clickhouse-connect` | lock 1.7.0, 동기 HTTP client 사용 |
| 스키마 | Postgres는 Alembic, ClickHouse는 번호 `.sql` |

`uv.lock`의 실제 고정 버전은 [`backend/uv.lock`](../../backend/uv.lock), 구조 선택의 근거는
설계 문서 [§10·§11.10·§12](../superpowers/specs/2026-08-12-gardevoir-design.md)에 있다.

### 현재 감사 경로

| 경로 | 현재 동작 | 중요한 성질 |
|---|---|---|
| read DAO | raw parameterized SQL을 동기 `Client.query()`로 실행하고 `asyncio.to_thread`로 감싼다 | 목록·단건·요약 세 질의, named result를 result DTO로 변환 |
| write sink | 인메모리 큐 뒤에서 `Client.insert()`로 행렬을 배치 삽입한다 | 일반 응답을 막지 않음, critical action은 큐 포화 시 동기 fallback, drain 보장 |
| schema | 시작 시 파일명 순으로 `.sql`을 실행한다 | 한 append-only 테이블, 각 문장은 idempotent여야 함 |

근거 코드는 [read DAO](../../backend/gateway/src/gateway/audit/infrastructure/dao/clickhouse_audit_dao.py),
[write sink](../../backend/gateway/src/gateway/audit/infrastructure/adapter/clickhouse_sink.py),
[schema 적용기](../../backend/gateway/src/gateway/audit/infrastructure/schema.py),
[`001_audit_events.sql`](../../backend/gateway/clickhouse/001_audit_events.sql)이다.

## 지원 생태계

SQLAlchemy 2.0이 본체에 포함하는 방언은 PostgreSQL, MySQL/MariaDB, SQLite, Oracle,
SQL Server이며 ClickHouse는 외부 방언이다. SQLAlchemy의
[외부 방언 목록](https://docs.sqlalchemy.org/en/20/dialects/index.html)은
`clickhouse-sqlalchemy`를 가리킨다. 다만 이 목록은 독점 추천이나 SQLAlchemy 프로젝트의
호환성 보증이 아니다. `clickhouse-connect`도 자체 entry point로 독립 방언을 제공한다.

### 배포·유지보수 현황

숫자는 조사 시점의 스냅숏이다. star 수보다 최근 릴리스, 기본 브랜치의 기능 커밋, 유지 주체를
더 강한 신호로 본다.

| 프로젝트 | 최신 PyPI 배포 | GitHub 상태 | 판단 |
|---|---|---|---|
| [`clickhouse-connect`](https://github.com/ClickHouse/clickhouse-connect) | [1.7.2](https://pypi.org/project/clickhouse-connect/), 2026-08-20 | 517 stars, 기본 브랜치 최근 커밋 2026-08-26, ClickHouse 공식·활발 | 주 후보 |
| [`clickhouse-sqlalchemy`](https://github.com/xzkostyan/clickhouse-sqlalchemy) | [0.3.2](https://pypi.org/project/clickhouse-sqlalchemy/), 2024-06-12 | 483 stars, 기본 브랜치 최근 커밋 2025-11-24, PyPI maintainer 1명 | 기능은 넓지만 배포·문서 신뢰도 낮음 |
| [`sqlalchemy-clickhouse`](https://github.com/cloudflare/sqlalchemy-clickhouse) | [0.1.5.post0](https://pypi.org/project/sqlalchemy-clickhouse/), 2018-08-09 | 325 stars, 마지막 기능성 커밋은 2020년; 2024년 변경은 Semgrep 설정 | 제외 |

`clickhouse-connect` 최신 upstream은 1.7.2지만 gardevoir lock은 1.7.0이다. 아래 최신 기능을
실제 도입안으로 옮길 때는 1.7.0에서 존재하는지 또는 별도 업그레이드가 필요한지 기능별로
다시 확인해야 한다. 이 문서는 의존성 변경을 제안하거나 수행하지 않는다.

### 기능 비교

| 항목 | `clickhouse-connect` 내장 방언 | `clickhouse-sqlalchemy` 0.3.2 |
|---|---|---|
| 접속 URL·전송 | `clickhousedb://`, 자체 HTTP driver | `clickhouse+http://`(`requests`), `clickhouse+native://`(`clickhouse-driver`), `clickhouse+asynch://`(`asynch`, Native TCP) |
| SQLAlchemy | 1.4와 2.x를 명시 지원. gardevoir 2.0.52와 방향이 맞음 | 0.3.x 패키지는 `sqlalchemy>=2.0,<2.1`을 요구. 그러나 0.3.2 문서는 1.4라고 적어 서로 모순 |
| Core | `SELECT`, JOIN, WHERE, 정렬, limit/offset, 집합 연산, lightweight DELETE, reflection | Core 조회·삽입, ALTER UPDATE/DELETE, reflection, ClickHouse 확장 |
| ClickHouse 조회 확장 | `FINAL`, `SAMPLE`, `PREWHERE`, `LIMIT BY`, `ARRAY JOIN`, GLOBAL/ANY/ASOF/SEMI/ANTI JOIN, lambda, materialized CTE | `FINAL`, `SAMPLE`, `LIMIT BY`, `ARRAY JOIN`, WITH CUBE/ROLLUP/TOTALS, JOIN strictness/distribution 등 |
| ORM | 선언 모델·단순 조회·insert·bulk insert만. full ORM 아님 | 선언 모델과 Session 조회·insert를 제공하지만 ClickHouse의 비트랜잭션·비관계형 성질은 그대로 |
| 주요 타입 | 정수·실수·Decimal·String·Enum·UUID·IP·Date/DateTime64·Array·Map·Tuple·JSON·Nested·AggregateFunction, `Nullable()`·`LowCardinality()` wrapper | Array·Nullable·LowCardinality·DateTime64·Map·Tuple·Enum·UUID·AggregateFunction 등 |
| 엔진·DDL | MergeTree 계열, Replicated/Shared 계열, Memory/Log/Distributed 등; database/table DDL·reflection | MergeTree 계열, Replicated 계열, Distributed/Buffer/View/Log/Memory 등; table/materialized view DDL·reflection |
| Alembic | 최신 버전은 autogenerate와 ClickHouse 전용 index·projection·table setting·materialized view·dictionary 작업 지원 | autogenerate는 가능하나 엔진 누락, nullable, materialized view 등 문서화된 수동 보정 범위가 큼 |
| 파라미터 | 기본은 client-side. `server_side_params=True`이면 typed `{name:Type}`를 생성하며 `SELECT`에 한정 | SQLAlchemy bind/DBAPI 파라미터. typed ClickHouse server-side placeholder를 방언의 주 계약으로 문서화하지 않음 |
| 트랜잭션 | commit/rollback은 서버에서 no-op | ClickHouse 자체에 전통적 트랜잭션이 없음 |
| async SQLAlchemy | **없음.** async client와 sync SQLAlchemy 방언은 별개 | `asynch` adapter가 `is_async=True`인 방언을 제공 |
| 의존성 영향 | 이미 쓰는 패키지와 SQLAlchemy를 재사용. 단, `Engine`을 새로 열면 별도 연결 소유자가 생김 | 패키지가 `requests`, `clickhouse-driver`, `asynch`를 모두 직접 요구하므로 사용하지 않는 전송까지 추가 |

`clickhouse-connect`의 범위와 한계는 [공식 SQLAlchemy 문서](https://clickhouse.com/docs/integrations/language-clients/python/sqlalchemy)와
[저장소 README](https://github.com/ClickHouse/clickhouse-connect#sqlalchemy-implementation),
`clickhouse-sqlalchemy`의 타입·엔진·쿼리 범위는
[기능 문서](https://clickhouse-sqlalchemy.readthedocs.io/en/latest/features.html)와
[연결 문서](https://clickhouse-sqlalchemy.readthedocs.io/en/latest/connection.html)를 기준으로 했다.

### `clickhouse-connect` 내장 방언

이 방언은 처음에는 Superset과 기본 Core 조회에 초점을 둔 가벼운 구현이었지만, 1.x에서
ClickHouse 전용 query construct, reflection, ORM의 제한적 insert/read, Alembic까지 범위가
넓어졌다. gardevoir에 필요한 `Array(LowCardinality(String))`, `DateTime64(3)`, `UInt*`,
`MergeTree(PARTITION BY ..., ORDER BY ...)`를 모두 표현할 수 있다.

장점은 이미 채택한 공식 driver 안에 있어 공급망과 전송이 늘지 않는다는 점이다. 최신
방언은 Core bulk insert도 지원하지만 공식 문서도 bulk 경로에서는 Core insert를 선호한다고
할 뿐, 기존 `Client.insert()`보다 낫다고 주장하지 않는다. 현재 sink는 SQL 문장 컴파일이
필요 없는 명시적 columnar batch 경로이므로 바꿀 이유가 없다.

중요한 한계는 다음과 같다.

- ORM의 unit of work, relationship, cascade, UPDATE, `RETURNING`, sequence는 지원하지 않는다.
- `primary_key=True`는 SQLAlchemy 객체 identity일 뿐 ClickHouse uniqueness나 sorting key가
  아니다. 실제 키는 table engine에 따로 선언한다.
- `engine.begin()`과 `Session.commit()`은 파이썬 코드의 구획일 뿐 서버 transaction이
  아니다.
- 일반 SQL 함수는 `func.countIf(...)`처럼 생성할 수 있지만, ClickHouse 함수의 인자·결과를
  모두 정적으로 검증해 주지는 않는다. 특히 gardevoir의 `map`, `JSONExtractBool`,
  `quantileTDigest` 결과 타입은 명시적 type annotation 또는 실제 결과 검증이 필요하다.
- SQLAlchemy 방언은 동기다. 공식 async client가 존재해도 `create_async_engine()`에는 연결되지
  않으며, [async SQLAlchemy 요청 #576](https://github.com/ClickHouse/clickhouse-connect/issues/576)은
  조사 시점에 열려 있다.

### `clickhouse-sqlalchemy`

기능 표면은 오래되고 넓다. Core와 선언 모델, ClickHouse 타입·엔진, materialized view,
ALTER UPDATE/DELETE, Alembic, HTTP·동기 Native TCP·async Native TCP를 하나의 방언 아래 둔다.
0.3.0 changelog는 SQLAlchemy 2.0 지원으로 전환했다고 밝히고 0.3.2 패키지도
`sqlalchemy>=2.0,<2.1`을 요구한다.

그러나 채택 신호는 좋지 않다.

- [0.3.2 문서](https://clickhouse-sqlalchemy.readthedocs.io/en/latest/)는 여전히
  “Supported SQLAlchemy: 1.4”라고 쓰며, 이 모순을 묻는
  [issue #340](https://github.com/xzkostyan/clickhouse-sqlalchemy/issues/340)은 답 없이 열려 있다.
- 최신 PyPI 0.3.2는 2024-06-12 배포다. 기본 브랜치에는 이후 수정이 있으나 새 0.3.x 배포가
  없다.
- 공개된 0.3.2 async adapter는 제거된 `asynch.connect()`를 호출한다. `asynch>=0.2.5`에서
  `Connection` 생성자를 쓰도록 고친
  [PR #381](https://github.com/xzkostyan/clickhouse-sqlalchemy/pull/381)은 2025-11-24에
  merge됐지만 아직 배포판에 없다. 최신 `asynch` 0.4.0과 공개 0.3.2의 async 조합은
  그대로 신뢰할 수 없다.
- HTTP 하나를 택해도 동기 Native driver와 async Native driver까지 필수 의존성으로 들어온다.
- Python 3.14가 프로젝트 분류·배포 조합으로 검증됐다는 증거가 없다. 하위 driver는 별도로
  3.14 wheel을 내지만 방언 통합은 다른 문제다.

따라서 “SQLAlchemy 2.0에서 async ClickHouse가 가능하다”는 존재 증명은 되지만,
gardevoir의 도입 후보로는 부적합하다.

### `sqlalchemy-clickhouse`

Cloudflare의 초기 방언이다. 최신 PyPI가 2018년 Python 2.7로 업로드됐고 classifier도
Python 2.7·3.4·3.5 시대에 머문다. 저장소의 최근 변경은 기능 유지보수가 아니다.
SQLAlchemy 2.0, Python 3.14, 현재 ClickHouse 타입을 검토할 가치보다 교체 위험이 크므로
즉시 제외한다.

## async 경로

“async client가 있다”와 “SQLAlchemy `AsyncEngine`을 쓸 수 있다”는 다른 주장이다. driver의
네트워크 I/O, SQLAlchemy 방언의 DBAPI adapter, gardevoir가 노출하는 coroutine API를 따로
보아야 한다.

| 조합 | 네트워크 I/O | SQLAlchemy query builder | gardevoir 관점 |
|---|---|---|---|
| 현재 `clickhouse-connect` sync + `to_thread` | `urllib3` 동기 HTTP를 worker thread에서 실행 | 없음 | 이미 검증된 최소 구조. 낮은 동시성에는 충분 |
| `clickhouse-connect` sync dialect + `to_thread` | 동기 HTTP를 worker thread에서 실행 | Core 가능 | query builder는 얻지만 thread는 없어지지 않음 |
| `clickhouse-connect.get_async_client()` | aiohttp 기반 asyncio-native HTTP; CPU parsing은 executor를 쓸 수 있음 | 없음 | 높은 동시성이 측정되면 가장 먼저 볼 async 후보 |
| `clickhouse-sqlalchemy` + `asynch` | asyncio Native TCP | Core/제한적 ORM + `AsyncEngine` | 기술적으로 가능하나 배포 호환성과 추가 운영면이 큼 |
| `asynch` 직접 사용 | asyncio Native TCP | 없음 | 활발하지만 공식 driver 교체와 TCP 포트·TLS·pool 운영이 추가 |
| `aiochclient` 직접 사용 | asyncio HTTP(S) | 없음 | 가벼운 대안이나 별도 driver를 더할 이유가 없음 |

### 현재 `to_thread`의 성질

현재 경로는 비동기 driver가 아니라 **이벤트 루프 비차단 adapter**다. 한 query/insert가 한
thread를 점유하고, coroutine을 취소해도 이미 시작된 blocking call 자체는 멈추지 않는다.
sink가 background task를 함부로 cancel하지 않고 drain하는 이유도 이것이다.

단점은 동시성이 커질 때 나타난다. thread pool 포화, thread stack 메모리, 스케줄링과 tail
latency 변동이 생길 수 있다. 반대로 현재 감사 조회는 console 요청이고 write는 이미 단일
배치 loop 뒤에 모인다. LLM 판정 hot path의 요청마다 ClickHouse query를 보내는 구조가
아니므로, async-native라는 이유만으로 driver를 바꿀 근거는 없다.

### `clickhouse-connect`의 async client

최신 공식 client는 aiohttp로 HTTP I/O를 수행한다. 기존 2024년 async wrapper는 sync client
전체를 executor에 올렸지만, 1.0부터 네트워크는 asyncio-native이고 Native format의 CPU
serialization/deserialization만 필요할 때 executor에서 수행한다. 공식
[advanced usage](https://clickhouse.com/docs/integrations/language-clients/python/advanced-usage#asyncclient)는
query, insert, raw, Arrow, streaming API의 parity를 선언한다.

ClickHouse의 [공식 benchmark 설명](https://clickhouse.com/blog/python-async-native-client)은
낮은 동시성에서는 sync-wrapper와 거의 같고, 동시성이 높고 결과가 클수록 throughput과 P95
안정성이 좋아졌다고 보고한다. 이 수치는 ClickHouse Cloud와 별도 하드웨어의 upstream
측정이므로 gardevoir의 근거 수치로 그대로 쓰지 않는다. 여기서 취할 결론은 방향뿐이다:
**thread pool 포화가 측정되기 전에는 전환 이득을 전제하지 않는다.**

이 client는 SQLAlchemy async 방언이 아니다. 따라서 Core와 async-native HTTP를 동시에
원하면 현재 공식 경로는 없다. SQLAlchemy statement를 따로 compile해 async client에
넘기는 방식은 parameter style과 dialect 내부 계약을 수동 연결하는 비표준 adapter가 되므로
권고하지 않는다.

### `asynch`와 `aiochclient`

[`asynch`](https://pypi.org/project/asynch/) 0.4.0은 2026-08-14 배포됐고 Native TCP,
connection pool, streaming, Python 3.11–3.14 및 Linux aarch64 wheel을 제공한다. GitHub는
244 stars이고 같은 날 기능 커밋이 있었다. 자체로는 SQLAlchemy 방언이 아니며,
`clickhouse-sqlalchemy`의 adapter를 통해서만 `AsyncEngine`과 결합한다. 앞서 본 미배포
호환 수정 때문에 두 프로젝트의 “각각 활발함”이 “공개 조합이 안전함”을 뜻하지 않는다.

[`aiochclient`](https://pypi.org/project/aiochclient/) 2.7.0은 2026-06-04 배포된 async
HTTP(S) client이고, [GitHub](https://github.com/maximdanilchenko/aiochclient)는 257 stars와
2026-06-08 최근 커밋을 보인다. SQLAlchemy 방언은 아니다. gardevoir가 이미 공식 HTTP
client를 쓰므로 같은 역할의 driver를 하나 더 넣을 이유는 없다.

## gardevoir 적용성

### read DAO를 Core로 옮길 때

현재 DAO의 raw SQL은 문자열 연결로 사용자 값을 삽입하지 않는다. 필드명과 식은 코드에
고정돼 있고 값은 `{name:Type}` server-side parameter다. 따라서 Core 도입의 주된 이점은
“SQL injection 해결”이 아니라 **질의 구조의 조합과 스키마 열의 중앙화**다.

| 얻는 것 | 잃거나 새로 부담하는 것 |
|---|---|
| 필터 조건·keyset pagination·공통 projection을 expression으로 재사용 | 현재 세 질의에는 추상화 양이 SQL보다 커질 수 있음 |
| 열 rename과 일부 Python result type을 한 `Table` 정의에 모음 | `.sql` 스키마와 `Table` metadata라는 두 표현의 drift 가능성 |
| 값 bind와 identifier quoting을 방언에 맡김 | 현재 typed parameter도 이미 값 bind와 escaping을 제공 |
| 동적 필터가 늘 때 문자열 조립 분기 감소 | ClickHouse 고유 함수는 대부분 `func.*`라 semantic type safety가 제한됨 |
| statement cache와 SQLAlchemy 공통 tooling | 새 sync `Engine`·pool·dispose 수명주기 필요 |
| 필요할 때 `text()` escape hatch | Core와 raw SQL이 섞이면 한 DAO 안에 두 문법이 생김 |

특히 현재 요약 질의는 effective action 식을 subquery에서 다시 쓰고 `map`, `countIf`,
`quantileTDigest`를 조합한다. Core로 표현할 수는 있지만 raw SQL보다 ClickHouse 의도가 더
잘 보인다고 단정할 수 없다. SQLAlchemy 타입이 함수의 ClickHouse 의미까지 검사하지도 않는다.

또한 기존 process-lifetime 자원은 하나의 `clickhouse-connect.Client`다. read만 sync
`Engine`으로 옮기고 sink를 `Client.insert()`로 남기면 ClickHouse transport 소유자가 둘이
되고 HTTP pool·close 경로도 둘이 된다. 이 비용을 피하려고 방언 내부 DBAPI connection에서
`Client`를 꺼내 sink와 공유하면 비공개 구현에 결합한다. read-only 파일럿은 이 두 pool을
의식적으로 허용하고 실제 자원 사용을 측정해야 한다.

따라서 지금은 raw SQL이 더 작고 정직하다. 다음 신호가 두 개 이상 나타날 때만 Core 파일럿을
연다.

- 감사 조회 endpoint와 공통 필터가 계속 늘어난다.
- 같은 projection·effective action 식이 여러 DAO에 복제된다.
- optional join, group, sort를 UI 요청에 따라 동적으로 조합해야 한다.
- raw SQL 변경에서 bind/type/column drift 결함이 반복된다.
- query builder가 필요한 별도 분석 consumer가 생긴다.

### write sink

write sink는 **그대로 둔다.** 현재 구조의 핵심은 ORM이 아니라 큐 정책과 배치다.

- 응답 경로는 `put_nowait`로 끝난다.
- ClickHouse가 원하는 큰 insert를 `Client.insert()` 한 번으로 보낸다.
- critical action의 유실 정책, stop/drain, `DateTime64(3)`에 `datetime`을 유지하는 규칙이
  코드에 명시돼 있다.
- column name과 행 순서가 노출돼 있어 `.sql` 스키마와의 위험한 불일치를 바로 볼 수 있다.

SQLAlchemy Core executemany가 bulk insert로 이어질 수 있어도 이 정책을 단순화하지 않는다.
ORM `Session.add_all()`은 identity map과 commit이라는 잘못된 관계형 어휘를 들여오며,
ClickHouse commit은 실제 transaction도 아니다. write 전환은 이득 없이 failure surface만
넓힌다.

### `.sql` 스키마와 Alembic

최신 `clickhouse-connect` Alembic 지원은 과거보다 훨씬 넓다. table/column 변화,
MergeTree 엔진, skip index, projection, setting, materialized view, dictionary를 다루며
autogenerate도 지원한다. 따라서 “ClickHouse라 Alembic이 원천적으로 불가능하다”는 결론은
이제 틀리다.

그럼에도 gardevoir는 **번호 `.sql`을 유지한다.** 이유는 현재 문제의 크기다.

1. 감사 스키마는 한 append-only 테이블이고 ClickHouse DDL 전체가 25줄 안에 보인다.
2. SQLAlchemy metadata를 read query 때문에 추가하면 `.sql`과 metadata 중 어느 것이 진실의
   출처인지 다시 정해야 한다.
3. ClickHouse migration은 Alembic을 써도 transaction rollback이 없다. 중간 실패의 부분
   적용과 forward repair를 설계해야 하는 본질은 바뀌지 않는다.
4. autogenerate 결과도 공식 문서가 매번 검토하라고 요구한다. 추상화가 ClickHouse DDL의
   운영 판단을 대신하지 않는다.
5. startup에서 idempotent 파일을 적용하는 현재 수명주기는 §12의 의도적 비대칭이다.

다만 현재 `CREATE TABLE IF NOT EXISTS`만으로는 기존 테이블을 진화시키지 못한다. 두 번째
schema change가 생길 때는 `002_*.sql`의 idempotent ALTER, 재실행 의미, 부분 실패 복구를
명시해야 한다. 테이블·view·projection·dictionary가 여러 개로 늘고 drift가 반복될 때
Alembic을 **조회 방언 도입과 별도 결정**으로 재평가한다.

## 권고와 단계적 판단 절차

### 지금

- raw parameterized SQL read DAO 유지
- `Client.insert()` write sink 유지
- 번호 `.sql` schema 유지
- `asyncio.to_thread` 유지
- 신규 방언·driver·Alembic extra 도입 안 함

### Core 재검토 조건이 생기면

1. `clickhouse-connect` 내장 방언만 후보로 둔다. `clickhouse-sqlalchemy`와 legacy 방언은
   비교 실험에서 제외한다.
2. 현 lock 1.7.0과 최신 upstream 사이에서 필요한 기능을 먼저 확정한다. 버전 업그레이드는
   별도 변경으로 취급한다.
3. `audit_events`의 read-only `Table` metadata를 만들고 `list_events` 한 질의만 Core로
   옮긴다. sink와 schema는 건드리지 않는다.
4. generated SQL, bind parameter, named result를 실제 ClickHouse 25.8에서 현재 raw 결과와
   비교한다.
5. raw/Core의 단건 latency뿐 아니라 동시 조회 P95, thread pool 대기, connection 수,
   process memory를 잰다.
6. 조합성 개선과 결함 감소가 숫자·변경 diff로 보일 때만 `get_event`, `summary` 순으로 넓힌다.
7. ClickHouse 고유 식이 Core에서 더 불명료해지는 부분은 `text()` 한 줄로 남길 수 있지만,
   escape hatch가 질의 대부분이 되면 파일럿을 되돌린다.

### async 재검토 조건이 생기면

감사 read 동시성 또는 thread pool 포화가 먼저 측정돼야 한다. 그때 SQLAlchemy와 묶지 말고
`clickhouse-connect.get_async_client()`로 현재 raw query/insert 계약을 보존하는 실험부터
한다. async extra의 `aiohttp`는 현재 lock에 없으므로 실제 전환은 분명한 의존성·수명주기
변경이다. sink의 ordering, drain, critical fallback, cancellation 의미를 다시 검증해야 한다.

## 라이브 실행이 필요한 항목

웹에서 패키지의 실재 여부, 최신 버전, 유지보수 상태, 선언된 지원 범위는 모두 확인했다.
다음은 자료 부족이 아니라 **이번 문서 작업이 설치·실행을 금지했기 때문에 남긴 runtime
검증 항목**이다.

1. gardevoir가 고정한 `clickhouse-connect==1.7.0` 방언이 SQLAlchemy 2.0.52와 Python
   3.14에서 현재 세 질의를 정확히 compile·execute하는지 확인한다.
2. `JSONExtractBool`, `map`, `countIf`, `quantileTDigest`, `Array(LowCardinality(String))`,
   `DateTime64(3)` bind와 result type을 raw SQL 결과와 비교한다.
3. `server_side_params=True`가 현재 `{name:Type}` 계약과 동일한 millisecond 정밀도를
   유지하는지 확인한다.
4. sync `Engine` 호출을 `to_thread`로 감쌀 때 pool/session ID/동시 connection과 shutdown이
   현재 단일 client 수명주기와 충돌하지 않는지 확인한다.
5. raw 대비 Core의 compile 포함 latency, 동시 조회 P95, memory와 connection 수를 이
   하드웨어에서 측정한다. 사전 성능 우열은 단정하지 않는다.
6. async 전환을 검토할 때 `clickhouse-connect[async]`의 insert drain, coroutine
   cancellation, server query 지속 여부, DateTime64 정밀도를 검증한다.
7. `clickhouse-sqlalchemy`를 다시 후보로 올릴 특별한 이유가 생기면 공개 0.3.2와
   `asynch` 0.4.0의 호환부터 확인한다. 현재 소스상으로는 미배포 수정 없이는 신뢰하지
   않는다.

## 주요 출처

- [SQLAlchemy 2.0 dialect 목록](https://docs.sqlalchemy.org/en/20/dialects/index.html)
- [`clickhouse-connect` PyPI](https://pypi.org/project/clickhouse-connect/) ·
  [GitHub](https://github.com/ClickHouse/clickhouse-connect) ·
  [SQLAlchemy 공식 문서](https://clickhouse.com/docs/integrations/language-clients/python/sqlalchemy) ·
  [async 공식 문서](https://clickhouse.com/docs/integrations/language-clients/python/advanced-usage#asyncclient)
- [`clickhouse-connect` 1.2.0 server-side bind release note](https://github.com/ClickHouse/clickhouse-connect/releases/tag/v1.2.0) ·
  [1.7.2 release](https://github.com/ClickHouse/clickhouse-connect/releases/tag/v1.7.2) ·
  [async SQLAlchemy issue #576](https://github.com/ClickHouse/clickhouse-connect/issues/576)
- [ClickHouse async-native client 설계·benchmark](https://clickhouse.com/blog/python-async-native-client)
- [`clickhouse-sqlalchemy` PyPI](https://pypi.org/project/clickhouse-sqlalchemy/) ·
  [GitHub](https://github.com/xzkostyan/clickhouse-sqlalchemy) ·
  [0.3.2 문서](https://clickhouse-sqlalchemy.readthedocs.io/en/latest/) ·
  [기능](https://clickhouse-sqlalchemy.readthedocs.io/en/latest/features.html) ·
  [migration 한계](https://clickhouse-sqlalchemy.readthedocs.io/en/latest/migrations.html)
- [`asynch` PyPI](https://pypi.org/project/asynch/) ·
  [GitHub](https://github.com/long2ice/asynch) ·
  [`aiochclient` PyPI](https://pypi.org/project/aiochclient/) ·
  [GitHub](https://github.com/maximdanilchenko/aiochclient)
- [`sqlalchemy-clickhouse` PyPI](https://pypi.org/project/sqlalchemy-clickhouse/) ·
  [GitHub](https://github.com/cloudflare/sqlalchemy-clickhouse)
