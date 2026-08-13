# 오염 추적 + ② tool_result 체크포인트 구현 계획 (Phase 3a)

설계 문서: §8(액션 통제 3단계), §7.4(무상태 오염 추적), §7.6(툴 등록), §10(감사).
선행: Phase 2 전체 — 머지됨.
후속: Phase 3b(④ tool_call 통제 + 인수 출처 검사).

## 이 단계가 막는 것

§8 의 공격은 ①도 ③도 정상이다. **②로 들어와 ④로 나간다.** 3a 는 그 ②쪽,
즉 "외부 데이터가 대화에 들어왔다"는 **구조적 사실**을 잡는다.

```
turn 1   사용자 질문                  깨끗함
turn 2   read_file 결과 도착           오염됨
turn 3   ...                          계속 오염 (되돌아가지 않음)
```

3a 산출물:

- 오염 여부를 매 요청 계산 (무상태, §7.4)
- ② tool_result 텍스트 검사 — 툴 결과에 심긴 지시를 regex 로 잡는다
- `TAINT` / `ALL` 노드 — 3b 의 "오염됨 AND 부작용 툴"을 조립할 부품
- 감사 로그의 `tainted` 컬럼을 실제 값으로 채운다 (§10 스키마에 이미 있다)

**3b 로 미루는 것:** ④ tool_call 체크포인트, 툴 분류, 인수 출처 검사, tool_call 차단.

## 범위 밖 — 승인은 이 단계가 아니다

§8 은 "차단 또는 승인 요구"라고 하고 승인이 실무의 정답인 경우가 많다고 한다.
그런데 §7.5 가 정직한 경계선을 그어 놨다:

```
앱 변경 0        차단(deny)·마스킹까지
앱 협조 필수      승인(ask) — 프록시는 사용자에게 화면을 띄울 수단이 없다
```

승인 흐름의 상세 설계는 §14 에서 미정이다. **Phase 3 은 deny 까지만 한다.**
`Action.APPROVAL_REQUIRED` 는 계약에 이미 있으니 Phase 6 이 채운다.

## Global Constraints

- 요청 경로다. Pydantic 금지, `orjson`, `re2`.
- **오염 추적에 저장소를 쓰지 않는다** (§7.4). `messages` 가 매 턴 전체로 오므로 매
  요청에서 새로 계산한다. Redis 도 세션 헤더도 없다.
- 오염은 **되돌아가지 않는다.** 한 번 오염되면 그 대화는 계속 오염이다.
- 새 노드도 컴파일되어 명령이 된다. 요청 경로에 그래프 순회가 없다 (§6).

## 계획 단계에서 확정한 결정

### 결정 1. 실행기가 텍스트 대신 `Subject` 를 받는다

②④는 텍스트만으로 판단할 수 없다. "대화가 오염됐나"는 텍스트가 아니라 **구조적
사실**이고, 3b 의 "어떤 툴인가"·"인수가 어디서 왔나"도 그렇다.

```python
@dataclass(frozen=True, slots=True)
class Subject:
    text: str = ""
    tainted: bool = False
    # 3b 가 tool_name, foreign_args 를 더한다
```

`execute(program, subject, *, collect_all)`. 텍스트만 필요한 곳은
`Subject(text=...)` 를 쓴다. dict 를 넘기지 않는 이유: 요청 경로에서 슬롯 dataclass
가 dict 보다 싸고, 필드가 계약이 되어야 3b 가 조용히 깨지지 않는다.

### 결정 2. 오염은 `role:tool` 메시지의 존재로 정한다

- `role == "tool"` 또는 `role == "function"`(구 프로토콜) 메시지가 하나라도 있으면 오염.
- assistant 의 `tool_calls` 만으로는 오염이 아니다 — **결과가 들어와야** 외부 데이터다.
- 오염 여부는 대화 전체의 성질이므로 체크포인트와 무관하게 같은 값이다.

### 결정 3. `TAINT` 는 소스, `ALL` 은 AND

`VERDICT` 의 여러 입력은 OR 다 (Phase 2b). §8 의 2단계는 "오염됨 **AND** 부작용 툴"
이므로 AND 가 필요하다.

| 노드 | 입력 | 출력 | 비고 |
|---|---|---|---|
| `taint` | 0 | bool | 소스다. extract 와 같은 자리 |
| `all` | 2 이상 | bool | 전부 참이면 참 |

`VERDICT` 에 `combine` 옵션을 두지 않는 이유: 노드로 두면 UI 가 그릴 수 있고,
`ALL` 의 출력을 여러 판정이 재사용할 수 있다.

### 결정 4. `TAINT` 는 텍스트 없이도 판정을 만들 수 있다

`taint -> verdict` 만으로 유효한 그래프다 — extract 가 없어도 된다. 그런데 Phase 2b 의
컴파일러는 **extract 에서 도달 가능한 노드**로 프로그램을 나눈다. 소스가 둘로 늘어나므로
분할 규칙을 "소스(extract 또는 taint)에서 도달 가능"으로 넓혀야 한다.

`taint` 는 체크포인트를 고르지 않는다(대화 전체의 성질). 그래서 `taint` 만 조상으로
갖는 부분 그래프는 **어느 체크포인트에 넣을지 정할 수 없다.** → `taint` 노드에
`checkpoint` 를 명시하게 한다. extract 와 같은 방식이라 컴파일러 분할이 그대로 돈다.

### 결정 5. ② 는 툴 결과 전체를 이어붙인다

①과 같은 이유다 (§7.4). 마지막 결과만 보면 여러 턴에 걸쳐 심은 것을 놓친다.
`role:tool` 메시지의 `content` 를 개행으로 이어붙인다.

### 결정 6. ② 차단은 400 이 아니다

① 은 사용자 입력이 문제라서 400(잘못된 요청)이 맞다. ② 는 **업스트림에 보내기 전**
단계이지만 문제가 사용자 요청이 아니라 대화에 들어온 외부 데이터다.

그래도 응답 시점은 ①과 같다(업스트림 호출 전). 형태를 ①과 같게 두면 앱이 구분할
필요가 없고, `gardevoir.checks` 와 감사 로그의 `checkpoint` 가 어디서 걸렸는지
말해준다. → **① 과 같은 400 + `error.code=content_filter`** 를 쓴다.

## File Structure

```
backend/gateway/src/gateway/
  domain/models/guardrail.py          (수정) VALID_CHECKPOINTS, TAINT/ALL, arity
  application/plan/execution_plan.py  (수정) Taint, All 명령
  application/plan/compiler.py         (수정) 소스 확장, TAINT/ALL 방출
  application/plan/executor.py         (수정) Subject
  application/inspection/text.py       (수정) extract_tool_result_text, is_tainted
  application/inspection/inspector.py  (수정) tool_result 체크포인트, Subject 조립
  application/service/proxy_service.py (수정) ② 배선, 감사 tainted
tests/
  test_guardrail_domain.py  test_compiler.py  test_executor.py
  test_inspection_text.py   test_inspector.py  test_proxy_inspection.py
```

---

## Task 1: 도메인 — 체크포인트 확장 + TAINT/ALL 노드

**Files:** `domain/models/guardrail.py`

**Produces:**
- `VALID_CHECKPOINTS = {"input", "output", "tool_result", "tool_call"}`
  (`tool_call` 은 3b 가 쓰지만 검증은 지금 넓혀 둔다 — 저작 UI 가 미리 만들 수 있다)
- `NodeType.TAINT`, `NodeType.ALL`
- `NODE_ARITY`: `TAINT (0,0)`, `ALL (2, MANY)`
- `_validate_taint` (checkpoint 필수), `_validate_all` (설정 없음)

- [x] Step 1~4: 테스트 → 실패 확인 → 구현 → 커밋

테스트 성질:
1. `test_tool_result_is_a_valid_checkpoint` / `test_tool_call_is_a_valid_checkpoint`
2. `test_an_unknown_checkpoint_is_still_rejected`
3. `test_taint_requires_a_checkpoint` — extract 와 같은 규칙
4. `test_taint_may_not_have_inputs` — 소스다
5. `test_all_requires_at_least_two_inputs` — 입력 하나면 AND 가 무의미하다
6. `test_all_accepts_many_inputs`
7. `test_a_taint_only_graph_validates` — `taint -> verdict`
8. `test_node_types_are_stable` — 저장된 그래프가 문자열로 남으므로 계약이다

---

## Task 2: 실행기 — Subject

**Files:** `application/plan/execution_plan.py`, `application/plan/executor.py`

**Produces:**
- `Taint(out: int)`, `All(out: int, srcs: tuple[int, ...])` 명령
- `Subject(text: str = "", tainted: bool = False)`
- `execute(program, subject: Subject, *, collect_all=False)`

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_taint_reports_the_subject_flag` (True/False 양쪽)
2. `test_all_is_true_only_when_every_input_is` (2입력 4조합)
3. `test_all_with_three_inputs`
4. `test_all_short_circuits_nothing_observable` — 결과만 본다
5. `test_a_taint_verdict_blocks_a_tainted_conversation`
6. `test_a_taint_verdict_allows_a_clean_conversation`
7. `test_taint_and_regex_combine_with_all` — §8 2단계의 모양
8. `test_subject_defaults_are_safe` — `Subject()` 는 오염 아님, 텍스트 빈 문자열
9. `test_execute_still_works_for_text_only_programs` — 회귀
10. `test_a_missing_text_does_not_crash_a_regex` — `Subject(tainted=True)` 만 준 경우

---

## Task 3: 컴파일러 — 소스 확장

**Files:** `application/plan/compiler.py`

**Produces:**
- 분할 규칙: **소스 = extract 또는 taint**. 둘 다 `config["checkpoint"]` 를 갖는다
- `Taint`/`All` 명령 방출
- `_COST`: `TAINT 0`(소스), `ALL 1`(bool 연산, 싸다)

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_a_taint_only_graph_compiles`
2. `test_taint_goes_to_its_checkpoint_program`
3. `test_a_verdict_reachable_from_taint_and_extract_on_one_checkpoint_compiles`
4. `test_a_verdict_mixing_checkpoints_via_taint_is_rejected` — `GUARDRAIL-013` 유지
5. `test_all_compiles_to_one_instruction`
6. `test_an_unreachable_taint_is_dropped`
7. `test_taint_comes_before_the_checks_that_read_it`
8. `test_a_mask_verdict_behind_all_is_rejected` — `GUARDRAIL-014` 유지 (위치를 모른다)
9. `test_slots_stay_dense_with_taint_and_all`
10. `test_the_order_is_still_hash_seed_independent` — 하위 프로세스 비교 (2b 성질)

---

## Task 4: 검사 — ② 체크포인트 + 오염 계산

**Files:** `application/inspection/text.py`, `application/inspection/inspector.py`

**Produces:**
- `is_tainted(payload) -> bool`
- `extract_tool_result_text(payload) -> str`
- `Inspector.tool_result(plan, payload, *, mode)` — ② 검사
- `Inspector` 가 모든 체크포인트에 `tainted` 를 실어 준다

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질 (text):
1. `test_a_tool_message_taints`
2. `test_a_function_message_taints` — 구 프로토콜
3. `test_an_assistant_tool_call_does_not_taint` — **결과가 들어와야** 외부 데이터다
4. `test_a_user_only_conversation_is_clean`
5. `test_taint_does_not_care_about_position` — 첫 턴에 있어도 마지막 턴에 있어도
6. `test_tool_result_text_joins_every_result`
7. `test_tool_result_text_ignores_other_roles`
8. `test_tool_result_text_reads_multimodal_parts`
9. `test_a_malformed_messages_list_is_clean` — 우리가 먼저 터지지 않는다

테스트 성질 (inspector):
10. `test_tool_result_checkpoint_runs`
11. `test_a_tainted_conversation_blocks_on_a_taint_verdict`
12. `test_the_input_checkpoint_also_sees_taint` — 오염은 대화 전체의 성질
13. `test_the_output_checkpoint_also_sees_taint`
14. `test_dry_run_reports_would_have_for_tool_result`
15. `test_tool_result_masking_is_not_supported` → 컴파일 시점에 이미 막혔는지 확인

---

## Task 5: 프록시 배선 + 감사

**Files:** `application/service/proxy_service.py`

**Produces:**
- ② 를 ① 다음, 업스트림 전에 돌린다
- 차단 형태는 ① 과 같다 (400 + `error.code=content_filter`)
- `inspected` 에 `tool_result` 추가
- 감사 로그의 `tainted` 를 실제 값으로

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 실제 기동 → 커밋 → 돌연변이

테스트 성질:
1. `test_a_blocked_tool_result_never_calls_upstream`
2. `test_a_blocked_tool_result_is_400`
3. `test_the_extension_reports_tool_result_inspected`
4. `test_audit_records_tainted_true`
5. `test_audit_records_tainted_false_for_a_clean_conversation`
6. `test_audit_checkpoint_is_tool_result_when_it_blocks`
7. `test_input_is_checked_before_tool_result` — ① 이 막으면 ② 는 돌지 않는다
8. `test_a_stream_also_checks_tool_result` — 업스트림 전이므로 스트리밍도 가능하다
9. `test_taint_is_reported_even_when_nothing_blocks` — 감사만 남는 경우

---

## Self-Review

**1. 계획 단계에서 고친 것**

- 처음에 `taint` 를 체크포인트 없는 전역 소스로 두려 했다. 그러면 `taint -> verdict`
  부분 그래프를 어느 체크포인트에서 실행할지 정할 수 없다 → extract 처럼
  `checkpoint` 를 명시하게 했다.
- `VERDICT` 에 `combine: any|all` 옵션을 두려 했다 → 노드로 분리했다. UI 가 그릴 수
  있고 `ALL` 출력을 여러 판정이 재사용한다.
- ② 차단을 새 상태 코드로 두려 했다 → ① 과 같은 400 이다. 어디서 걸렸는지는
  `checks` 와 감사 로그의 `checkpoint` 가 말한다. 앱이 구분할 이유가 없다.
- 승인(ask)을 이 단계에 넣으려 했다. §7.5 가 "앱 협조 필수"라고 못 박았고 상세 설계가
  §14 에서 미정이다 → deny 까지만.

**2. 위험**

- `Subject` 도입이 `execute` 시그니처를 바꾼다. 2b/2c 테스트가 전부 텍스트를 넘긴다 →
  한 번에 고치고, 텍스트 전용 프로그램이 그대로 도는지 회귀 테스트로 고정한다.
- 컴파일러의 "소스" 개념이 넓어진다. 2b 의 해시 시드 무관 결정론이 깨지지 않는지
  같은 방식(하위 프로세스 비교)으로 다시 확인한다.
- 오염은 되돌아가지 않으므로, 긴 대화에서 한 번 툴을 쓰면 이후 전부 오염이다.
  그것이 설계 의도다(§8) — 오탐 비용은 3b 의 "부작용 툴에만 적용"으로 줄인다.

**3. 열어두는 것**

- 툴 분류의 저장 위치는 3b 에서 정한다. §7.6 은 "게이트웨이 쪽, 보안 담당자가 설정"
  만 요구하므로, 그래프 노드 설정에 두면 발행·버전·롤백·감사가 공짜로 따라온다.
  대신 가드레일 간 중복이 생기고, 그 답은 §5 의 `SharedNode` 다.
- 오염 등급(어느 툴에서 왔나)은 두지 않는다. §8 은 이진 사실만 쓴다.

---

## 실행 결과 (2026-08-13)

전부 완료. `feat/phase3a-taint-tracking`. 764 tests (gateway 708 + shared_kernel 56).

### §8 의 공격이 실제로 막힌다

실제 uvicorn + Postgres + ClickHouse, 폴링 주기 600초(즉시 반영만 통과 가능).

정책: `taint(tool_result) AND regex("발송하십시오|보고할 필요 없") → block`

```
[400] 계약서 요약해줘 + 오염된 툴 결과      blocked  inspected=['tool_result']  checks=['v']
[200] 계약서 요약해줘 + 깨끗한 툴 결과      allow    (정상 업무는 통과)
[200] 툴 없이 같은 질문                    allow
[200] 사용자가 직접 그 지시문을 입력        allow    ← 오염이 없으므로 ② 는 안 걸린다
```

마지막 줄이 `ALL` 이 하는 일이다. 사용자가 같은 문구를 타이핑한 것은 외부 데이터가
아니므로 ② 의 대상이 아니다 — 그건 ① 의 일이다.

감사 로그:

```
action     checkpoint    tainted  checks   v
blocked    tool_result   1        ['v']    1
allow      tool_result   1        []       1
allow      tool_result   0        []       1
```

게이트웨이 추가 지연 0.03~0.15 ms.

### 돌연변이 테스트

22개 중 CAUGHT 19, SURVIVED 1, SKIP 2(돌연변이 문자열이 안 맞은 하네스 실수).

생존자 하나가 실제 구멍이었다: **감사 `checkpoint` 의 `TOOL_RESULT` 분기를 지워도
통과했다.** ② 프로그램만 있는 그래프에서는 ①이 돌지 않아서, 폴스루가 어느 분기로
답해도 `tool_result` 가 나온다. ①도 도는 그래프에서 ②가 막는 테스트를 추가했다 —
분기가 빠지면 ②가 막은 것을 ①로 기록하고, 정책 튜닝은 "어디서 걸렸나"를 믿고 하는
일이다.

### 계획에서 바뀐 것

계획대로 갔다. 계획 단계에서 이미 세 가지를 고쳐 뒀기 때문이다:

- `taint` 에 `checkpoint` 를 명시하게 한 것 — 없으면 `taint -> verdict` 부분 그래프를
  어느 체크포인트에서 실행할지 정할 수 없다.
- `ALL` 을 노드로 분리한 것 — `VERDICT` 의 여러 입력은 OR 이고 §8 2단계는 AND 다.
- ② 차단을 ①과 같은 400 으로 둔 것.

구현 중 추가로 정한 것: `Subject.tainted` 의 기본값을 **False** 로 뒀다. 보통은
"기본을 안전한 쪽으로"가 맞지만, 오염은 **차단의 근거**이므로 기본을 True 로 두면
오염을 계산하지 않은 경로가 전부 차단된다. 테스트 독스트링에 이유를 적었다.

### 3b 로 넘기는 것

- ④ tool_call 체크포인트, 툴 분류(§7.6), 인수 출처 검사(§8 3단계), tool_call 차단
- 툴 분류의 저장 위치는 3b 에서 정한다. 그래프 노드 설정에 두면 발행·버전·롤백·감사가
  공짜로 따라오고, 대신 가드레일 간 중복이 생긴다 (§5 의 `SharedNode` 가 답)
