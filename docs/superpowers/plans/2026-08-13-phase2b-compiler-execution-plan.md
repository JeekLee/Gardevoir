# 컴파일러 + 실행 계획 구현 계획 (Phase 2b)

설계 문서: `docs/superpowers/specs/2026-08-12-gardevoir-design.md` §4, §6, §11.2~11.6.
선행: Phase 2a (저작·검증·발행) — 머지됨.
후속: Phase 2c (프록시 경로에 ①③ 통합).

## 범위

발행된 가드레일 그래프를 **프로세스 메모리의 실행 계획으로 컴파일**하고, 그 계획을
**그래프를 걷지 않고** 실행한다. HTTP 통합은 2c 다 — 이 단계의 산출물은 순수 함수와
프로세스 수명 레지스트리이므로 HTTP 없이 전부 테스트된다.

**범위 밖**

- 프록시 경로 연결, 체크포인트 호출 시점 (2c)
- 모델 티어 — 힌트형/모델형 판정의 *실행* (Phase 4). 이 단계는 "모델이 필요하다"는
  사실만 결과에 담는다
- 오염 추적, tool_result/tool_call 체크포인트 (Phase 3)
- `SharedNode`, `BaseGuardrail` 병합 — 참조하는 것이 아직 없다
- 홀드백/스트리밍 (Phase 4), 승인 (Phase 6)

## Global Constraints

요청 경로에 들어가는 코드다. `skills/gardevoir-be` 의 요청 경로 제약이 그대로 적용된다.

- **Pydantic 금지.** 계획·명령·결과는 전부 `@dataclass(frozen=True, slots=True)` (§11.8).
- **`import re2`, `orjson`.**
- **요청당 DB·네트워크 0회.** 실행은 dict 조회 한 번 + 배열 순회다 (§6).
- **명령이 원본 노드 dict 를 붙들지 않는다.** §11.6 의 307 KB 가 그래서 나왔다.
  필요한 필드만 명령에 담는다.
- 컴파일은 발행·기동 시점에만 돈다. 컴파일 경로에는 Pydantic 을 써도 되지만 쓸 일이 없다.

## 핵심 설계 결정 (계획 단계에서 확정)

### 1. 체크포인트별로 프로그램을 나눈다

한 계획에 프로그램 하나를 두면 실행할 수 없다. ①입력은 업스트림 호출 **전**,
③출력은 **후** 라서 시점이 다르고, 한 배열을 두 시점에 걸쳐 실행할 수는 없다.

따라서 컴파일 산출물은 `checkpoint -> Program` 이다. 각 프로그램은 그 체크포인트의
`extract` 노드에서 도달 가능한 부분 그래프다.

**결과로 얻는 것:** 어떤 가드레일이 출력을 보지 않으면 `program_for("output")` 이
`None` 이고, 2c 는 그 체크포인트를 통째로 건너뛴다.

### 2. 체크포인트를 섞는 verdict 는 검증 오류다

`input` 분기와 `output` 분기를 동시에 입력으로 받는 verdict 는 두 시점 중 어디서도
평가할 수 없다. 늦은 쪽에서 평가하려면 이른 쪽 결과를 요청 사이에 들고 있어야 하고,
그것이 바로 Phase 3 의 오염 추적이다.

지금 반쯤 구현하는 것보다 **경계를 명시하고 거부하는** 편이 낫다 → `GUARDRAIL-013`.

### 3. 노드 입력 개수(arity)를 도메인이 검증한다

컴파일러가 "입력이 정확히 하나"를 가정할 수 있어야 한다. 2a 는 끊긴 엣지와 순환만
봤다.

| 노드 | 입력 |
|---|---|
| `extract` | 0 — 소스다 |
| `regex`, `length`, `transform` | 정확히 1 |
| `verdict` | 1 이상 (여러 개면 OR) |

`Guardrail.validate()` 에 넣는다 → 저작 시점과 발행 시점 양쪽에서 걸린다.
컴파일 시점에 처음 터지면 "발행이 문법 오류로 실패"하는데, §6 이 피하려던 것이 그것이다.

### 4. 조기 종료는 enforce 에서만 한다

§6 런타임 스니펫은 `BLOCK` 에서 `break` 한다. 그런데 §4 는 "걸린 체크 전부를 남겨라 —
하나만 남기면 정책 튜닝이 불가능해진다"고 한다. 둘이 충돌한다.

모드로 가른다. `enforce` 는 어차피 막으므로 조기 종료가 맞고, `dry-run` 은 튜닝이
존재 이유이므로 전부 돌아야 한다. 실행기가 `collect_all` 을 받는다.

### 5. 미해결 힌트를 실행기가 처리하지 않는다

규칙 티어는 막아/통과/**모르겠음** 세 답을 낸다 (§4). 모델 티어가 없는 지금
"모르겠음"을 실행기가 allow 로 바꿔버리면, Phase 4 가 붙을 때 그 결정이 어디서
났는지 찾을 수 없게 된다.

실행기는 `pending_model` 에 담아서 넘긴다. 그것을 어떻게 처리할지는 호출자(2c)가
한 곳에서 결정하고 감사 로그에 남긴다.

### 6. regex 합침은 "읽는 슬롯"으로 묶는다

같은 슬롯을 읽는 regex 노드들을 `re2.Set` 하나로 합쳐 1패스로 검사한다.
실측(이 하드웨어, 패턴 200개 / 2 KB 문서): **Set 0.0046 ms vs 개별 루프 0.365 ms (80배)**.

API: `re2.Set.SearchSet()` → `Add(pattern)` 이 인덱스 반환 → `Compile()` →
`Match(text)` 가 매치된 인덱스 `list` 또는 **`None`** 반환. `None` 을 빈 리스트로
착각하면 조용히 전부 통과한다.

그룹 크기가 1이면 Set 을 만들지 않는다 (`re2.compile` 이 더 싸다).

## File Structure

```
backend/gateway/src/gateway/
  domain/models/guardrail.py            (수정) arity 검증
  domain/exception/guardrail_error.py   (수정) 012, 013
  application/
    plan/__init__.py
    plan/execution_plan.py              ExecutionPlan, Program, 명령 dataclass
    plan/compiler.py                    compile_guardrail()
    plan/executor.py                    execute(), ExecutionResult
    plan/registry.py                    PlanRegistry
    port/guardrail_source.py            GuardrailSource Protocol
  infrastructure/plan/__init__.py
  infrastructure/plan/guardrail_source.py   세션 스코프 어댑터
  settings.py                           (수정) plan_poll_interval_s
tests/
  test_execution_plan.py  test_compiler.py  test_executor.py
  test_plan_registry.py   test_guardrail_source.py
  test_plan_performance.py
```

`application/plan/` 이 `service/` 가 아닌 이유: 컴파일러와 실행기는 유스케이스가
아니라 순수 변환이다. 서비스 클래스로 감싸면 상태 없는 함수에 DI 를 붙이는 셈이 된다.

---

## Task 1: arity 검증 (컴파일러의 전제)

**Files:** `domain/models/guardrail.py`, `domain/exception/guardrail_error.py`

**Produces:**
- `GuardrailError.INVALID_ARITY = ("GUARDRAIL-012", ..., ValidationError)`
- `Guardrail._validate_arity()` — `validate()` 에서 호출

- [ ] Step 1~4: 테스트 → 실패 확인 → 구현 → 커밋

테스트 성질:
1. `test_extract_may_not_have_inputs`
2. `test_regex_requires_exactly_one_input` (0개, 2개 각각)
3. `test_length_requires_exactly_one_input`
4. `test_transform_requires_exactly_one_input`
5. `test_verdict_requires_at_least_one_input`
6. `test_verdict_accepts_many_inputs`
7. `test_the_arity_error_names_the_node` — `details.node_id`
8. `test_an_empty_graph_still_validates` — 노드 0개는 유효 (2a 성질 유지)
9. `test_arity_runs_on_publish` — 서비스 경유

---

## Task 2: ExecutionPlan + 명령

**Files:** `application/plan/execution_plan.py`

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class Extract:   out: int; checkpoint: str
class Transform: out: int; src: int; op: str
class Length:    out: int; src: int; max_chars: int
class RegexOne:  out: int; src: int; pattern: object          # re2 컴파일 결과
class RegexSet:  outs: tuple[int, ...]; src: int; matcher: object
class Verdict:   srcs: tuple[int, ...]; decision: Decision; action: VerdictAction; node_id: str

Instruction = Extract | Transform | Length | RegexOne | RegexSet | Verdict

@dataclass(frozen=True, slots=True)
class Program:
    instructions: tuple[Instruction, ...]
    slot_count: int

@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    guardrail: str
    version_number: int
    programs: dict[str, Program]          # checkpoint -> Program
    def program_for(self, checkpoint: str) -> Program | None
    @property
    def checkpoints(self) -> frozenset[str]
```

`Verdict` 에 `out` 이 없다. 판정은 슬롯이 아니라 결과 목록으로 모인다 — 판정에는
bool 이 아니라 action·decision·node_id 가 필요하다.

`node_id` 를 명령에 담는 이유: 감사 로그의 `checks_fired` 가 정책 튜닝의 유일한
입력이다 (§4). 원본 노드 dict 를 붙들지 않으려면 필요한 필드만 복사해야 한다 (§11.6).

- [ ] Step 1~4

테스트 성질:
1. `test_program_for_returns_none_for_an_unused_checkpoint`
2. `test_checkpoints_lists_only_what_the_plan_inspects`
3. `test_instructions_are_immutable` — `FrozenInstanceError`
4. `test_instructions_have_slots` — `__dict__` 없음. §11.8 의 메모리 성질
5. `test_an_instruction_does_not_hold_the_source_node` — 명령 필드에 dict 없음

---

## Task 3: 컴파일러

**Files:** `application/plan/compiler.py`

**Produces:** `compile_guardrail(guardrail: Guardrail) -> ExecutionPlan`

단계 (§6 의 ②~⑨, 노드 문법 검증 제외):

```
① 체크포인트별 부분 그래프 분할     extract 에서 도달 가능한 노드
② 섞인 verdict 거부                GUARDRAIL-013
③ 위상 정렬                        Kahn
④ 도달 불가 노드 제거              verdict 로 가지 못하는 노드는 실행할 이유가 없다
⑤ 슬롯 배정                        노드 id -> 배열 인덱스 (프로그램별)
⑥ regex 합침                       읽는 슬롯이 같은 것끼리 re2.Set
⑦ 비용순 재정렬                    의존성 안에서 싼 것 먼저
⑧ 명령 생성
```

**④를 넣는 이유:** verdict 에 닿지 않는 노드는 결과에 영향이 없다. UI 에서 노드를
그려두고 연결을 안 한 상태가 흔하므로 실전에서 자주 발생한다.

**⑦ 비용 순서:** `length < transform < regex`. 조기 종료가 빨라진다.
위상 순서를 깨뜨리지 않는 범위에서만 재정렬한다 (레벨 안에서 안정 정렬).

- [ ] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_a_single_checkpoint_graph_compiles`
2. `test_each_checkpoint_gets_its_own_program`
3. `test_a_verdict_mixing_checkpoints_is_rejected` — `GUARDRAIL-013`
4. `test_unreachable_nodes_are_dropped` — verdict 없는 분기가 명령에 없다
5. `test_a_graph_with_no_verdict_compiles_to_an_empty_program`
6. `test_slots_are_dense` — `slot_count` 가 실제 쓰이는 슬롯 수와 같다
7. `test_regexes_reading_the_same_slot_are_merged` — `RegexSet` 하나
8. `test_regexes_reading_different_slots_are_not_merged`
9. `test_a_lone_regex_is_not_wrapped_in_a_set` — `RegexOne`
10. `test_instructions_respect_dependencies` — 소스가 항상 먼저
11. `test_cheaper_instructions_come_first_within_a_level`
12. `test_compiling_twice_yields_equivalent_programs` — 결정론적
13. `test_the_plan_records_the_version_number` — 감사 로그가 이것을 박는다 (§6)
14. `test_transform_chains_compile` — transform → regex

---

## Task 4: 실행기

**Files:** `application/plan/executor.py`

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class ExecutionResult:
    action: VerdictAction
    checks_fired: tuple[str, ...]
    pending_model: tuple[str, ...]

def execute(program: Program, text: str, *, collect_all: bool = False) -> ExecutionResult
```

판정 우선순위 `block > mask > allow` (§4. `approval_required` 는 Phase 6).

- 결론형(`CONCLUSIVE`)이 걸리면 그 action 이 후보가 된다
- 힌트형/모델형이 걸리면 `pending_model` 에 들어간다 — 실행기가 판정하지 않는다
- `collect_all=False` 이고 결론형 BLOCK 이 나오면 즉시 종료

- [ ] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_a_clean_text_is_allowed`
2. `test_a_matching_regex_blocks`
3. `test_the_fired_node_is_reported`
4. `test_a_regex_set_fills_only_matching_slots` — **`Match` 가 `None` 을 준다**
5. `test_length_fires_over_the_limit` / `test_length_does_not_fire_at_the_limit` (경계)
6. `test_transform_feeds_the_next_check` — `lower` 뒤 대문자 패턴이 안 걸린다
7. `test_block_beats_mask`
8. `test_mask_beats_allow`
9. `test_a_hint_does_not_decide` — action 은 allow, `pending_model` 에 남는다
10. `test_a_model_only_verdict_always_pends`
11. `test_enforce_stops_early` — BLOCK 뒤 명령이 실행되지 않는다 (관측 가능하게 구성)
12. `test_dry_run_collects_every_check` — 같은 그래프에서 `checks_fired` 가 더 많다
13. `test_an_empty_program_allows`
14. `test_a_verdict_with_many_inputs_is_an_or`
15. `test_execution_does_not_mutate_the_plan` — 계획은 재사용된다. 두 번 돌려 같은 결과
16. `test_slots_do_not_leak_between_runs`

---

## Task 5: PlanRegistry (원자적 교체)

**Files:** `application/plan/registry.py`, `application/port/guardrail_source.py`,
`infrastructure/plan/guardrail_source.py`, `settings.py`

**Produces:**

```python
class GuardrailSource(Protocol):                      # application/port
    async def latest_versions(self) -> dict[str, int]
    async def load_published(self, name: str, version_number: int) -> Guardrail | None

class PlanRegistry:
    def get(self, name: str) -> ExecutionPlan | None  # 요청 경로. dict 조회 한 번
    async def refresh(self, name: str) -> ExecutionPlan | None
    async def load_all(self) -> int
    async def start(self) -> None                     # 폴러
    async def stop(self) -> None
```

**원자적 교체 (§6):** `self._plans[name] = plan` 한 줄. 요청은 시작할 때 `get()` 으로
잡은 계획을 끝까지 쓴다 — 입력을 v37, 출력을 v38 로 검사하면 판정이 앞뒤가 안 맞고
재현이 불가능해진다. **그 규칙을 지키는 것은 2c 이지만, 계획 객체가 불변이어야
가능하므로 여기서 고정한다.**

**폴링:** 워커는 별도 프로세스라 한 워커의 발행이 다른 워커에 보이지 않는다.
§14 가 "`LISTEN/NOTIFY` 는 후속, 폴링으로 시작"이라 했다. `latest_versions()` 를
주기적으로 읽어 번호가 바뀐 것만 재컴파일한다.

**세션:** 레지스트리는 프로세스 수명, 세션은 요청 수명이다.
`SessionScopedGuardrailSource` 가 호출마다 짧은 세션을 연다 —
`SessionScopedApiKeyRepository`(1c)와 같은 패턴이다.

- [ ] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_get_returns_none_for_an_unknown_guardrail`
2. `test_load_all_compiles_every_published_guardrail`
3. `test_load_all_skips_a_guardrail_with_only_a_draft`
4. `test_refresh_swaps_in_the_new_version`
5. `test_a_held_plan_is_unaffected_by_a_swap` — **먼저 잡은 계획으로 끝까지**
6. `test_get_does_not_touch_the_source` — 요청 경로에 DB 0회. 호출 수를 센다
7. `test_the_poller_picks_up_a_new_publish`
8. `test_the_poller_ignores_an_unchanged_version` — 재컴파일 0회
9. `test_the_poller_survives_a_source_failure` — 예외로 루프가 죽지 않는다
10. `test_a_compile_failure_keeps_the_previous_plan` — 새 발행이 깨졌다고 운영 중인
    계획을 잃으면 안 된다
11. `test_stop_is_idempotent`
12. `test_the_poller_does_not_block_the_event_loop` — 1c 에서 배운 대로, 동시에
    돌리는 ticker 의 벽시계로 측정한다
13. `test_source_opens_a_session_per_call` (`test_guardrail_source.py`)

---

## Task 6: 실측 — §11 을 구현으로 다시 잡는다

**Files:** `tests/test_plan_performance.py`, 설계 문서 §11 갱신

§11.3/§11.4/§11.6 은 **프로토타입** 실측이다. 실제 구현으로 다시 재고, 다르면 문서를
고친다. §11 의 숫자 때문에 구조가 정해진 곳이 여러 곳이므로 (`AGENTS.md`), 숫자가
낡으면 그 근거가 낡는다.

측정 항목:

| 항목 | 문서 값 | 확인할 것 |
|---|---|---|
| 계획 1개 컴파일 | 10.16 ms → 문법 검증 제외 시 ~4.5 ms | 저작 시점 이동이 실제로 절반을 줄였나 |
| 요청당 실행 | 0.618 ms | 컴파일된 계획의 실제 비용 |
| 그래프를 걷는 방식 | 6.200 ms | 10배 차이가 재현되나 |
| `re2.Set` vs 개별 | 0.0086 / 4.399 ms | 이 하드웨어에서 80배 (개별을 re2 로 재면) |
| 계획 1개 메모리 | 307 KB | 노드 dict 를 안 붙들면 얼마나 줄었나 |

성능 테스트는 **회귀 감시**로만 둔다 — 절대값을 단정하면 다른 하드웨어에서 깨진다.
넉넉한 상한(예: 실행 5 ms, 컴파일 100 ms)만 걸고, 실제 숫자는 문서에 기록한다.

- [ ] Step 1~3: 측정 → 문서 갱신 → 커밋

---

## Self-Review

**1. 2b 와 2c 의 경계**

실행기는 `Program` 과 `text` 만 받는다. "어느 시점에 무슨 텍스트를 뽑는가"는 2c 다.
그래서 이 단계는 HTTP 없이 전부 테스트되고, 2c 는 배선만 남는다.

**2. 계획 단계에서 고친 것**

- 처음에 프로그램 하나로 두려 했다. ①은 업스트림 전, ③은 후라서 한 배열을 두 시점에
  걸쳐 실행할 수 없다는 것을 뒤늦게 봤다 → 체크포인트별 프로그램.
- 미해결 힌트를 실행기가 allow 로 바꾸려 했다. 그러면 Phase 4 가 붙을 때 그 결정이
  어디서 났는지 찾을 수 없다 → `pending_model` 로 넘긴다.
- 조기 종료를 무조건 하려 했다. §4 의 "걸린 체크 전부"와 충돌한다 → dry-run 은 전부.
- arity 검증을 컴파일러에 두려 했다. 그러면 발행이 실패할 수 있고, §6 이 문법 검증을
  저작 시점으로 옮긴 이유가 사라진다 → 도메인.

**3. 위험**

- `re2.Set.Match` 가 매치 없을 때 `None` 을 준다. 빈 리스트로 착각하면 조용히 전부
  통과한다 — 가드레일에서 가장 나쁜 실패 방향이다. 테스트 4번이 이것을 고정한다.
- 폴러가 이벤트 루프를 막으면 프록시 지연이 폴링 주기마다 튄다. 1c 의 ClickHouse
  싱크에서 같은 함정을 겪었고, 그때 배운 측정 방법(동시 ticker 의 벽시계)을 쓴다.
- 컴파일 실패가 운영 중인 계획을 날리면, 잘못된 발행 하나가 가드레일을 없앤다.
  테스트 10번.

**4. 열어두는 것**

- 슬롯별 regex 재합침(§11.4, §14): 상위 노드 출력을 읽는 regex 도 슬롯 번호로 묶을
  수 있다. ⑥이 이미 "읽는 슬롯"으로 묶으므로 구조상 공짜로 얻는다.
- LRU 계획 캐시(§6): `get`/`refresh` 인터페이스가 그대로다.
- `SharedNode`/`BaseGuardrail` 병합: 컴파일 입력이 `Guardrail` 하나이므로, 병합은
  컴파일 앞단에 함수 하나로 들어간다.
