# Alembic으로 ClickHouse 마이그레이션을 관리할 수 있는가

**조사일** 2026-08-27

**대상** gardevoir의 PostgreSQL·ClickHouse 스키마 수명주기

**상태** 도입 판단 자료 — 구현 제안이 아님

## 결론

**기술적으로는 가능하다.** Alembic 자체가 ClickHouse를 아는 것은 아니지만 SQLAlchemy
방언이 reflection, DDL compiler, Alembic operation·autogenerate hook을 제공하면 버전
마이그레이션을 실행할 수 있다. 두 후보 모두 이 통합을 실제로 제공한다.

- `clickhouse-sqlalchemy`는 0.1.10부터 Alembic과 제한적 autogenerate를 지원한다.
- gardevoir가 이미 쓰는 공식 `clickhouse-connect`도 1.1.0부터 Alembic 통합을 제공한다.
  현재 고정 버전 1.7.0에는 테이블·컬럼·MergeTree 엔진뿐 아니라 skip index, projection,
  table setting, materialized view, dictionary용 operation까지 들어 있다.

그러나 **gardevoir에는 지금 도입하지 않는다.** 현재 ClickHouse 스키마는 append-only
`audit_events` 한 테이블이고, 23줄짜리 `001_audit_events.sql`을 시작 시 멱등 적용한다.
Alembic이 주는 revision history와 drift detection보다 별도 metadata·migration env·배포
단계·부분 실패 복구라는 새 비용이 더 크다. 무엇보다 ClickHouse DDL 여러 문장을 하나로
묶어 되돌리는 transaction은 없으므로, Alembic을 붙여도 중간 실패와 데이터 손실을
PostgreSQL처럼 rollback할 수 없다.

지금의 권고는 다음과 같다.

1. PostgreSQL은 기존 Alembic을 그대로 사용한다.
2. ClickHouse는 번호가 붙은 멱등 `.sql`을 계속 진실의 출처로 둔다.
3. 두 번째 스키마 변경이 생기면 `002_*.sql`을 재실행 가능한 forward migration으로
   작성한다. `IF EXISTS`·`IF NOT EXISTS`만으로 의미가 보장되지 않는 변경은 적용 전후
   상태 검사와 복구 절차를 함께 정한다.
4. ClickHouse 객체와 변경 빈도가 늘어 migration history·drift detection의 가치가 실제로
   커질 때 `clickhouse-connect`로 다시 검토한다. 그때도 PostgreSQL과 **완전히 분리된
   Alembic env와 revision lineage**를 `--name`으로 선택하는 구성이 맞다.

## 조사 기준과 현재 구조

버전·기능 범위는 2026-08-27에 upstream 문서, PyPI, GitHub release와 소스를 확인했다.
브리프가 라이브러리 설치와 migration 실행을 금지하므로 후보 패키지를 새로 설치하거나
ClickHouse에 DDL을 실행하지 않았다. 문서에 적은 “지원”은 upstream이 선언하고 구현한
범위이며, gardevoir의 정확한 버전 조합에서 남은 실행 검증은 마지막 절에 분리한다.

| 항목 | 현재 값 | 스키마 수명주기 |
|---|---|---|
| PostgreSQL | 17, SQLAlchemy 2.0.52 async | Alembic 1.19.1 |
| ClickHouse | 25.8, `clickhouse-connect` 1.7.0 | 번호 `.sql`을 시작 시 파일명 순으로 멱등 적용 |
| 감사 스키마 | `audit_events` 한 테이블 | `MergeTree`, 월 partition, `(app_name, created_at, id)` 정렬키 |

구조 선택의 근거는 설계 문서 [§10·§12](../superpowers/specs/2026-08-12-gardevoir-design.md)에
있다. PostgreSQL은 가변 상태와 transaction을, ClickHouse는 고용량 append-only 감사
이벤트와 분석 질의를 소유한다. 그래서 §12는 의도적으로 “SQLAlchemy/Alembic은
Postgres, `clickhouse-connect`는 감사”로 수명주기를 갈랐다.

현재 경로는 다음과 같다.

- PostgreSQL [`alembic/env.py`](../../backend/gateway/alembic/env.py)는 async psycopg engine을
  만들고, `gateway`의 `infrastructure` package를 걸어 ORM model을 빠짐없이 등록한 뒤
  `Base.metadata`를 비교한다.
- ClickHouse [`schema.py`](../../backend/gateway/src/gateway/audit/infrastructure/schema.py)는
  [`backend/gateway/clickhouse`](../../backend/gateway/clickhouse)의 `.sql`을 정렬하고 각
  문장을 `Client.command()`로 실행한다. 적용 이력을 DB에 기록하지 않고 매번 모두
  재실행하므로 각 문장이 멱등이어야 한다.
- 현재 [`001_audit_events.sql`](../../backend/gateway/clickhouse/001_audit_events.sql)은
  `CREATE TABLE IF NOT EXISTS` 하나다. 기존 테이블을 진화시키는 문장은 아직 없다.
- 감사 read DAO는 이미 `clickhouse-connect.cc_sqlalchemy` 타입과 방언으로 SQLAlchemy Core
  문장을 compile하지만 SQLAlchemy `Engine`을 열지는 않는다. DAO의 private `MetaData`에는
  조회 열만 있고 MergeTree engine·partition·sorting key가 없으므로 그대로 Alembic의
  schema metadata가 될 수 없다.

마지막 점은 중요하다. SQLAlchemy 방언을 query compiler로 쓰고 있다는 사실이 Alembic
도입을 공짜로 만들지는 않는다. Alembic은 완전한 ClickHouse schema metadata, live
reflection, 별도 connection과 version table을 추가로 요구한다.

## Alembic과 ClickHouse가 결합되는 방식

Alembic은 migration engine이면서 SQLAlchemy 방언의 소비자다. 일반적인 operation을
ClickHouse SQL로 compile하고, live schema와 `MetaData`를 비교하며, ClickHouse에 맞는
version table을 관리하는 부분은 외부 방언이 채워야 한다. URL만 ClickHouse로 바꾼 일반
Alembic env로는 충분하지 않다.

### `clickhouse-connect`

공식 ClickHouse Python driver인 `clickhouse-connect`는 `clickhousedb://` SQLAlchemy
방언 안에 Alembic 통합도 함께 제공한다.

- [1.1.0 release](https://github.com/ClickHouse/clickhouse-connect/releases/tag/v1.1.0)는
  2026-05-26 처음 Alembic 통합을 정식 배포했다. create/drop table, add/alter/drop/rename
  column, type·nullability·default·comment, `IF EXISTS`, `AFTER`, operation setting,
  MergeTree 계열 engine과 dictionary의 autogenerate·upgrade·downgrade round trip을
  명시한다.
- [1.5.0 release](https://github.com/ClickHouse/clickhouse-connect/releases/tag/v1.5.0)는
  skip index, projection, table setting, materialized view와 dictionary용 operation을
  추가했다. gardevoir 고정 버전 1.7.0은 이 이후 버전이다.
- 조사 시점 최신 안정판은
  [1.7.2](https://github.com/ClickHouse/clickhouse-connect/releases/tag/v1.7.2)다. SQLAlchemy
  2.x reflection과 DDL escaping 수정이 계속 들어오고 있어 프로젝트는 활발하지만,
  Alembic 통합 자체는 정식 배포 후 석 달밖에 되지 않은 젊은 기능이다.

공식 [worked example](https://github.com/ClickHouse/clickhouse-connect/blob/main/clickhouse_connect/cc_sqlalchemy/alembic/WORKED_EXAMPLE.md)은
일반 env와 다른 설정을 요구한다.

- `clickhouse_connect.cc_sqlalchemy.alembic`을 import해 통합을 등록한다.
- ClickHouse용 `target_metadata`를 따로 제공한다.
- `include_name`으로 대상 database를 제한하고, `include_object`로 일반 SQLAlchemy index
  같은 비호환 객체를 거른다.
- `clickhouse_writer`가 generated revision에 ClickHouse import를 넣는다.
- 호환되는 `alembic_version` table을 ClickHouse 안에 만든다.

공식 설치 표기는 `clickhouse-connect[alembic]`이다. gardevoir는 이미
`clickhouse-connect`, SQLAlchemy, Alembic을 각각 직접 의존하고 버전 요구조건도 충족하지만,
현재 선언 그대로 통합 import와 모든 operation이 동작하는지는 라이브 검증 대상이다. 이
문서는 dependency 표기를 바꾸지 않는다.

지원 범위가 넓어도 모든 ClickHouse DDL을 추상화하지는 않는다. 특히 공식 example은
`ON CLUSTER`를 helper 범위 밖으로 명시하고 `op.execute()` raw SQL을 쓰라고 한다. 결국
Alembic은 ClickHouse 문법을 없애는 계층이 아니라 **revision 순서와 일부 DDL 생성을
관리하는 실행기**다.

### `clickhouse-sqlalchemy`

`clickhouse-sqlalchemy`도 실제 Alembic 통합을 갖고 있다. 따라서 “비공식 방언이라
Alembic이 아예 안 된다”는 설명은 틀리다.

- [migration 문서](https://clickhouse-sqlalchemy.readthedocs.io/en/latest/migrations.html)는
  0.1.10부터 Alembic을 지원한다고 밝힌다.
- autogenerate는 table·materialized view와 column의 추가·삭제, table·column comment를
  감지한다.
- 문서 자체가 generated migration을 수동 조정해야 한다고 말한다. engine은
  `op.create_table`에 포함되지 않고, `Column(nullable=True)`의 `Nullable(T)` 생성도
  지원하지 않으며, Atomic database의 변경된 materialized view `SELECT`에도 제한이 있다.
- 표현할 수 없는 객체는 결국 `op.execute()` raw SQL로 작성한다.

조사 시점 PyPI의 가장 높은 버전은
[0.3.2](https://pypi.org/project/clickhouse-sqlalchemy/)(배포 2024-06-12)이고 development status는
Beta다. 0.3.2 package는 SQLAlchemy 2.0을 요구하지만 최신 문서는 여전히 “Supported
SQLAlchemy: 1.4”라고 적어 배포 metadata와 문서가 모순된다. 기존
[방언 조사](2026-08-27-clickhouse-sqlalchemy.md)가 기록한 async adapter의 미배포 호환
수정과 추가 driver 의존성까지 고려하면 새로 채택할 이유가 없다.

| 판단 항목 | `clickhouse-connect` 1.7.x | `clickhouse-sqlalchemy` 0.3.2 |
|---|---|---|
| 유지 주체 | ClickHouse 공식, 활발 | 개인 maintainer 중심, 0.3.x 배포 정체 |
| gardevoir dependency | 이미 사용 | 신규 방언·driver 추가 |
| Alembic 통합 성숙도 | 범위는 넓지만 2026-05 첫 정식 배포 | 오래됐지만 문서화된 autogenerate 공백이 큼 |
| ClickHouse 고유 DDL | engine·index·projection·setting·MV·dictionary | engine 누락 등 수동 보정 범위가 큼 |
| `ON CLUSTER` | raw `op.execute()` | 일부 operation parameter, 나머지는 raw SQL |
| gardevoir 후보 | **재검토 시 유일한 후보** | 제외 |

## ClickHouse DDL이 만드는 한계

### migration 전체를 감싸는 transaction이 없다

ClickHouse는 일부 operation에 statement 단위 atomicity를 제공한다. 예를 들어 공식
[`ALTER COLUMN` 문서](https://clickhouse.com/docs/sql-reference/statements/alter/column)는
한 `ALTER`가 atomic이라고 설명한다. 이것을 PostgreSQL의 transactional DDL과 혼동하면
안 된다.

ClickHouse의 [experimental transaction 문서](https://clickhouse.com/docs/guides/developer/transactional)는
table 생성 DDL을 transaction 밖에서 실행하라고 명시한다. 따라서 revision 안의 DDL A가
성공하고 DDL B가 실패하면 A만 적용된 상태가 남는다. `context.begin_transaction()`이
Alembic env에 있어도 방언에서 논리적 구획일 뿐 서버의 migration-wide rollback이 아니다.

이 차이는 `alembic_version`에도 적용된다. schema DDL은 성공했는데 version row 갱신 전
연결이 끊기면, 다음 실행은 같은 revision을 다시 시도할 수 있다. 그래서 Alembic을 쓰더라도
각 forward operation을 가능한 한 멱등하게 만들고, 재실행 전 현재 상태를 판별하며, 한
revision에 unrelated DDL을 많이 묶지 않아야 한다.

### `ALTER TABLE`의 비용과 제약이 operation마다 다르다

| 변경 | ClickHouse 의미 | migration·downgrade 결과 |
|---|---|---|
| `ADD COLUMN` | metadata만 바꾸며 기존 part는 읽을 때 default를 계산한다 | 빠르고 멱등화하기 쉽다. 나중에 materialize하면 별도 mutation 비용이 든다 |
| `DROP COLUMN` | column 파일을 삭제하며 materialized view가 참조하면 거부된다 | 빠르지만 데이터는 사라진다. downgrade의 재추가는 데이터 복원이 아니다 |
| `RENAME COLUMN` | data를 건드리지 않지만 sorting/primary key expression의 열은 rename할 수 없다 | inverse rename은 가능해도 consumer rollout 순서를 별도로 풀어야 한다 |
| `MODIFY COLUMN TYPE` | 값을 새 타입으로 변환하고 저장 파일을 바꾼다 | 큰 테이블에서는 오래 걸리고 변환 실패·정밀도 손실 때문에 대칭 downgrade를 보장할 수 없다 |
| `MATERIALIZE`·data mutation | part를 background에서 다시 쓴다 | 비동기 진행과 I/O 비용이 있고 제출 뒤 rollback할 수 없다 |

공식 [`ALTER` 문서](https://clickhouse.com/docs/sql-reference/statements/alter)는 mutation이
part 단위로 비동기 진행되고, 진행 중 query가 변경 전·후 part를 함께 볼 수 있으며, 제출된
mutation을 rollback할 방법은 없다고 설명한다. `KILL MUTATION`은 아직 하지 않은 작업을
멈출 뿐 이미 바뀐 part를 원복하지 않는다. `system.mutations`, `mutations_sync`,
`alter_sync`를 migration 완료 판단에 포함해야 하는 이유다.

### MergeTree의 핵심 키는 일반 컬럼 변경이 아니다

현재 `audit_events`의 월 partition과 sorting key는 단순 schema 장식이 아니라 물리 배치와
retention의 계약이다.

- [`MODIFY ORDER BY` 문서](https://clickhouse.com/docs/sql-reference/statements/alter/order-by)는
  sorting key 변경이 metadata-only라고 설명하지만, 기존 열을 사용한 새 식을 추가할 수
  없다. 같은 `ALTER`에서 default 없이 새로 추가한 열만 새 sorting expression에 넣을 수
  있고 primary key는 그대로다.
- primary key는 생성 뒤 일반 `ALTER` 대상으로 바꿀 수 없다.
- `ALTER ... PARTITION`은 partition의 drop·move·replace 같은 data 관리 operation이지
  `PARTITION BY` expression 변경이 아니다. partition key나 table engine을 바꾸는 일반적
  경로는 새 table 생성, data backfill, 검증, rename/exchange다.

따라서 autogenerate가 metadata 차이를 발견하는 것과 안전한 migration 계획을 생성하는 것은
다르다. key·engine·partition 변경은 Alembic operation 한 줄보다 shadow table, dual write
또는 ingest 중지, backfill, cutover와 복구 계획의 문제다.

### cluster에서는 성공의 뜻도 넓어진다

현재 gardevoir Compose는 단일 ClickHouse 25.8 `MergeTree`라 이 문제가 당장 없지만,
`ReplicatedMergeTree`나 cluster로 확장하면 migration 계약이 달라진다.

ClickHouse [distributed DDL 문서](https://clickhouse.com/docs/sql-reference/distributed-ddl)는
`ON CLUSTER` query가 각 host에서 결국 실행되고 **한 host 안의 실행 순서만** 보장한다고
설명한다. 일시적으로 host별 schema가 다를 수 있고, 실패·비활성 replica는 distributed DDL
queue와 replication queue를 따로 확인해야 한다. `clickhouse-connect` Alembic helper가
`ON CLUSTER`를 의도적으로 자동 생성하지 않는 이유도 이 운영 결정을 방언이 대신할 수 없기
때문이다.

## autogenerate와 downgrade를 신뢰할 수 있는 범위

### autogenerate는 초안이다

Alembic autogenerate는 live reflection과 원하는 `MetaData`의 차이를 operation 초안으로
만든다. ClickHouse에서는 다음을 사람이 검토해야 한다.

- MergeTree engine, `PARTITION BY`, `ORDER BY`, TTL, setting이 정확히 round trip했는가
- `LowCardinality`, `Nullable`, `DateTime64(3)`, nested container type이 의도대로
  compile됐는가
- default 변경이 과거 part의 값을 실제로 바꿔야 하는가, 읽을 때만 달라져도 되는가
- type 변경과 materialization이 얼마만큼의 part rewrite를 만드는가
- drop으로 보이는 차이가 metadata 등록 누락이 아닌가
- single node SQL인지 `ON CLUSTER`·replication wait가 필요한 SQL인지

특히 현재 PostgreSQL env의 package walk를 ClickHouse에 재사용하면 안 된다. 그 walk는
`Base.metadata`를 완성해 PostgreSQL model 누락을 없애기 위한 장치다. ClickHouse env는
감사 schema만 담은 별도 metadata를 명시적으로 가져야 한다. 두 metadata를 한 autogenerate
대상으로 합치면 PostgreSQL table을 ClickHouse에 만들거나 ClickHouse table을 drop하라는
잘못된 diff가 생긴다.

현재 DAO의 `_AUDIT_EVENTS`도 조회 compiler의 열 목록이지 schema definition이 아니다.
이를 migration source로 승격하려면 engine, partition, sorting key, nullability, default,
TTL까지 완전하게 표현하고 query와 migration이 함께 참조할 공개 소유 위치를 먼저 정해야
한다. `.sql`과 별도 metadata를 동시에 진실의 출처로 두면 drift 검출을 도입하면서 새 drift
원인을 만드는 셈이다.

### downgrade는 rollback이 아니라 inverse DDL 실행이다

`alembic downgrade` 명령이 존재한다는 사실은 데이터가 원복된다는 보장이 아니다.

- `ADD COLUMN`의 inverse인 `DROP COLUMN`은 그동안 쌓인 새 데이터를 삭제한다.
- `DROP COLUMN` 뒤 `ADD COLUMN`은 이름과 타입만 되살리고 과거 값은 복원하지 못한다.
- narrowing type conversion은 정보 손실이나 실패를 만들 수 있다.
- partition·primary key·engine cutover는 한 문장 inverse가 없다.
- 이미 실행된 mutation은 downgrade revision이 새 mutation을 실행할 뿐 취소되지 않는다.

ClickHouse revision은 **forward-only를 기본 정책**으로 두는 편이 정직하다. 정말 안전하고
대칭인 metadata 변경에만 downgrade를 제공하고, destructive 변경은 명시적으로
irreversible하게 두며 backup·shadow table·forward repair로 복구해야 한다. 배포 뒤 공유된
revision file을 삭제하거나 history를 다시 쓰는 방식은 피한다.

## PostgreSQL과 ClickHouse를 함께 관리하는 Alembic 구성

두 DB는 한 애플리케이션에 있지만 schema model, driver, transaction, 배포 실패 의미가
다르다. “프로젝트가 하나”는 migration lineage를 합칠 이유가 아니다.

### 선택지 비교

| 구성 | 모양 | 장점 | 문제 |
|---|---|---|---|
| 별도 env + `--name` | PostgreSQL·ClickHouse마다 `env.py`, `versions/`, `alembic_version`; 한 `alembic.ini`의 named section으로 선택 | 독립 history, dialect별 hook과 metadata, DB별 배포·복구 | 명령을 두 번 실행하고 운영 절차도 둘을 구분해야 함 |
| 별도 config file | env와 ini까지 완전 분리하고 `-c`로 선택 | 가장 강한 격리 | 공통 logging 등 설정 중복 |
| 단일 `multidb` env | 한 revision에 `upgrade_postgres()`·`upgrade_clickhouse()`를 함께 생성 | 한 명령으로 두 DB를 진행 | cross-DB transaction 없음, 서로 다른 dialect hook 결합, 한쪽 실패 시 release 상태가 더 모호 |
| 한 env + 여러 version location | 여러 revision branch가 한 version table을 공유 | 같은 DB 안의 multiple base에는 유용 | 독립 DB를 표현하는 도구가 아니며 이 경우에 부적합 |

Alembic 공식
[`--name` cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#run-multiple-alembic-environments-from-one-ini-file)은
서로 완전히 독립된 revision history와 각자의 `alembic_version` table을 가진 여러 DB에
named section과 별도 `script_location`을 쓰는 방식을 제공한다. 공식 `multidb` template도
존재하지만 한 revision에서 여러 engine을 함께 움직여야 할 때의 구조다.

gardevoir에 도입한다면 다음 모양을 권고한다.

- 기존 `[alembic]`과 `backend/gateway/alembic/`은 PostgreSQL 전용으로 그대로 둔다. 기존
  `alembic upgrade head`의 의미를 바꾸지 않는다.
- `[clickhouse]` named section은 별도 ClickHouse env와 versions directory를 가리킨다.
  ClickHouse 명령에만 `alembic --name clickhouse ...`를 요구한다.
- PostgreSQL env는 지금처럼 async psycopg와 `Base.metadata` package walk를 사용한다.
- ClickHouse env는 sync `clickhousedb` connection, `ch_alembic` hook, 감사 전용 metadata를
  사용한다.
- 두 upgrade를 release 절차가 순서대로 호출할 수는 있지만 원자적 한 작업으로 가장하지
  않는다. 어느 DB까지 적용됐는지를 각각 관찰하고 재실행할 수 있어야 한다.

## 멱등 `.sql`과 Alembic의 gardevoir 득실

| 기준 | 현재 번호 `.sql` | 별도 ClickHouse Alembic |
|---|---|---|
| 진실의 출처 | ClickHouse DDL 자체 | 완전한 SQLAlchemy metadata + revision |
| 이력 | git 파일 순서만 있고 DB 적용 version은 없음 | DB별 current/history와 revision graph |
| 시작·신규 환경 | 매 기동 전체 재실행, 멱등이면 단순 | 배포 단계에서 `upgrade head`, version table 필요 |
| drift 발견 | 자동 비교 없음 | reflection 기반 autogenerate/check 가능 |
| ClickHouse 문법 | 전부 직접 표현 | 공통 operation은 helper, 공백은 `op.execute()` |
| 실패 복구 | 멱등 재실행·수동 forward repair | revision 위치는 알지만 DDL transaction이 없어 결국 멱등 재실행·forward repair 필요 |
| downgrade | 제공하지 않음 | 함수는 쓸 수 있으나 데이터 복원은 보장하지 않음 |
| runtime 소유 | 기존 process client 하나 | migration용 SQLAlchemy connection과 별도 env 추가 |
| 운영 복잡도 | 현재 한 파일·한 테이블에 작음 | metadata, version table, 명령, 권한, 배포 serialization 추가 |

현재 방식에도 한계는 있다. `schema.py`가 반환하는 “applied” filename은 DB에 남는 이력이
아니며, `CREATE TABLE IF NOT EXISTS`는 이미 존재하는 table의 열·engine·key drift를
고치거나 알려 주지 않는다. 여러 process가 동시에 시작해도 문장이 멱등이어야 하며,
semicolon split도 복잡한 SQL로 커지면 별도 parser 없이 안전하지 않다.

그럼에도 현재 문제에는 충분하다.

1. schema가 append-only table 하나라 전체 DDL을 한 화면에서 검토할 수 있다.
2. 변경 빈도가 낮고 아직 두 번째 migration도 없다.
3. 시작 시 `CREATE TABLE IF NOT EXISTS`는 신규 환경 bootstrap과 다중 replica 기동에 잘
   맞는다.
4. Alembic을 붙여도 가장 중요한 failure mode인 partial DDL과 destructive change를
   없애지 못한다.
5. application startup bootstrap만으로 끝나던 ClickHouse에 별도 migration 배포 단계가
   추가된다.

따라서 revision graph가 해결할 실제 문제가 생기기 전에 도구부터 늘릴 값어치가 없다.

## 재검토 조건과 도입한다면 지킬 단계

다음 신호가 두 개 이상 나타날 때 Alembic을 다시 검토한다.

- ClickHouse table, materialized view, dictionary, projection이 여러 개로 늘어난다.
- schema 변경이 반복되고 환경별 적용 여부를 filename만으로 판단하기 어려워진다.
- live schema drift가 실제 장애나 잘못된 query 결과를 만든다.
- application startup DDL보다 독립된 schema rollout·승인·감사가 필요해진다.
- table rebuild와 backfill을 여러 환경에서 같은 순서로 추적해야 한다.

도입한다면 순서는 다음과 같다.

1. 후보는 `clickhouse-connect` 하나로 한정한다. 현재 1.7.0을 검증할지, 1.7.2 이상의
   reflection fix가 필요한지 먼저 결정하고 version 변경은 별도 작업으로 둔다.
2. `audit_events`의 완전한 schema metadata를 만든다. read DAO와 공유하되 migration
   definition의 소유 위치와 engine·partition·sorting key를 빠뜨리지 않는다.
3. PostgreSQL과 분리된 ClickHouse env·versions·version table을 만들고 `--name`으로만
   실행한다. 단일 `multidb` revision은 쓰지 않는다.
4. 기존 환경은 `SHOW CREATE TABLE`, `system.columns`, engine·key·setting을 canonical
   metadata와 대조한 뒤 baseline한다. `stamp`는 schema를 검증하거나 고치지 않고 version만
   기록하므로 검증 전에 실행하지 않는다.
5. migration은 한 번에 한 deployment job만 실행한다. application replica마다 startup에서
   Alembic을 경쟁 실행하지 않는다.
6. 모든 forward revision은 partial apply 뒤 재실행할 수 있게 작성한다. destructive
   operation은 backup·shadow table·cutover·forward repair를 먼저 설계하고 downgrade를
   억지로 채우지 않는다.
7. Alembic이 schema의 소유권을 넘겨받는 release에서 기존 startup `.sql` 적용기의 역할을
   종료한다. 두 경로가 같은 객체를 계속 관리하게 두지 않는다. 멱등성은 별도 raw 파일을
   남기는 방식이 아니라 Alembic revision operation 자체에 보존한다.

## 라이브 확인이 필요한 항목

웹에서 패키지 실재 여부, 버전, 선언된 기능과 ClickHouse DDL 의미는 확인했다. 다음은 이번
작업의 “설치·migration 실행 금지” 때문에 의도적으로 실행하지 않은 검증이다.

1. Python 3.14, SQLAlchemy 2.0.52, Alembic 1.19.1,
   `clickhouse-connect==1.7.0`, ClickHouse 25.8 조합에서 `ch_alembic` import와 online/offline
   env가 동작하는지 확인한다.
2. 빈 DB에서 initial autogenerate가 `DateTime64(3)`,
   `Array(LowCardinality(String))`, `MergeTree`, `PARTITION BY toYYYYMM(created_at)`,
   `ORDER BY (app_name, created_at, id)`를 손실 없이 생성하는지 확인한다.
3. 기존 `001_audit_events.sql`로 만든 DB를 reflection했을 때 no-op revision이 나오는지,
   current lock 1.7.0과 upstream 1.7.2 reflection fix의 차이가 있는지 확인한다.
4. compatible `alembic_version` table이 ClickHouse 25.8에서 생성·조회·갱신되고 application
   DB user 권한으로 충분한지 확인한다.
5. add/default, rename, type change, drop을 복제 data에서 실행해 소요 시간, part rewrite,
   `system.mutations`, 기존 행의 default 의미와 generated downgrade의 데이터 손실을
   확인한다.
6. DDL 성공 직후 version row 갱신 전 연결 종료를 재현해 같은 revision 재실행과
   forward repair 절차를 확인한다.
7. cluster 도입 시에만 `ON CLUSTER`, inactive replica, `alter_sync`·`mutations_sync`,
   distributed DDL queue를 포함한 별도 검증을 한다. 현재 단일-node gardevoir의 도입
   판단을 위해 cluster를 미리 구성할 필요는 없다.

## 주요 출처

- [Alembic 1.19.1 migration environment](https://alembic.sqlalchemy.org/en/latest/tutorial.html) ·
  [`--name` multiple environments](https://alembic.sqlalchemy.org/en/latest/cookbook.html#run-multiple-alembic-environments-from-one-ini-file) ·
  [multiple-engine autogenerate](https://alembic.sqlalchemy.org/en/latest/api/autogenerate.html#revision-generation-with-multiple-engines-run-migrations-calls)
- [`clickhouse-connect` 1.1.0 release](https://github.com/ClickHouse/clickhouse-connect/releases/tag/v1.1.0) ·
  [1.5.0 release](https://github.com/ClickHouse/clickhouse-connect/releases/tag/v1.5.0) ·
  [Alembic worked example](https://github.com/ClickHouse/clickhouse-connect/blob/main/clickhouse_connect/cc_sqlalchemy/alembic/WORKED_EXAMPLE.md) ·
  [PyPI](https://pypi.org/project/clickhouse-connect/)
- [`clickhouse-sqlalchemy` migration 문서](https://clickhouse-sqlalchemy.readthedocs.io/en/latest/migrations.html) ·
  [PyPI](https://pypi.org/project/clickhouse-sqlalchemy/) ·
  [GitHub](https://github.com/xzkostyan/clickhouse-sqlalchemy)
- [ClickHouse transaction](https://clickhouse.com/docs/guides/developer/transactional) ·
  [`ALTER COLUMN`](https://clickhouse.com/docs/sql-reference/statements/alter/column) ·
  [`ALTER`와 mutation](https://clickhouse.com/docs/sql-reference/statements/alter) ·
  [`MODIFY ORDER BY`](https://clickhouse.com/docs/sql-reference/statements/alter/order-by) ·
  [`ON CLUSTER`](https://clickhouse.com/docs/sql-reference/distributed-ddl)
- gardevoir [SQLAlchemy ClickHouse 방언 조사](2026-08-27-clickhouse-sqlalchemy.md) ·
  [설계 §10·§12](../superpowers/specs/2026-08-12-gardevoir-design.md)
