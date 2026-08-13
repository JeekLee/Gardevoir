# 프록시 경로 통합 구현 계획 (Phase 2c)

설계 문서: §3(체크포인트), §4(2티어), §7.2~7.3(계약), §9(스트리밍), §10(감사).
선행: 2a(저작·발행), 2b(컴파일러·실행 계획) — 둘 다 머지됨.
후속: Phase 3(액션 통제 ②④), Phase 4(모델 티어 + 홀드백).

## 범위

컴파일된 계획을 **실제 요청 경로에 붙인다.** ① 입력 검사와 ③ 출력 검사가 돌고,
차단이 §7.3 의 응답 형태로 나가고, 감사 로그에 판정이 남는다.

**범위 밖**

- ② tool_result / ④ tool_call, 오염 추적 (Phase 3)
- 모델 티어의 실제 판정 (Phase 4) — `pending_model` 은 받아서 기록만 한다
- 스트리밍 홀드백 (Phase 4) — 아래 "결정 2" 참조
- 승인 흐름 (Phase 6)

## Global Constraints

- 요청 경로다. Pydantic 금지, `orjson`, `re2`. 계획 조회는 dict 한 번 (§6).
- **요청 하나는 시작할 때 잡은 계획을 끝까지 쓴다** (§6). 입력을 v37, 출력을 v38 로
  검사하면 판정이 앞뒤가 안 맞고 재현이 불가능해진다. 계획을 한 번 잡아서 넘긴다.
- `finish_reason` 은 표준 값만. 확장은 전부 `gardevoir` 객체로 (§7.3, §11.9).
- **업스트림에는 우리 헤더도 우리 크레덴셜도 가지 않는다** (1c 에서 확립).

## 계획 단계에서 확정한 결정

### 결정 1. MASK 는 추출 텍스트를 직접 읽는 패턴만 허용한다

실행기는 "걸렸다/안 걸렸다"만 안다. 마스킹은 **위치**가 필요하다.
`re2.Set.Match` 는 어느 패턴이 걸렸는지만 주고 어디인지는 주지 않는다.

위치를 얻으려면 걸린 패턴을 원본에 다시 돌려야 한다. 그런데 그 패턴이 `transform`
출력(예: 소문자화)을 읽었다면 원본에서는 안 걸릴 수 있다. 그러면 `action=mask` 라고
응답하면서 실제로는 아무것도 가리지 않는다 — **조용한 fail-open** 이고, 가드레일에서
가장 나쁜 실패 방향이다.

따라서 **MASK 판정은 extract 를 직접 읽는 regex 에만 의존할 수 있다.** 위반은
컴파일 시점에 `GUARDRAIL-014` 로 거부한다. 런타임에 그 상황이 올 수 없게 만든다.

MASK 를 아예 Phase 4 로 미루지 않는 이유: 지금 미루면 MASK 판정이 걸렸을 때 allow
(fail-open) 또는 block (과차단) 중 하나로 조용히 처리된다. 둘 다 저작자가 쓴 정책과
다르다.

### 결정 2. 스트리밍은 출력 검사를 하지 않고, 그 사실을 응답에 밝힌다

③ 출력 검사는 홀드백이 있어야 의미가 있고(§9), 홀드백은 Phase 4 다.
그런데 가드레일에 출력 프로그램이 있는데 스트리밍이라 검사하지 않았다면, 호출자는
검사된 줄 안다. **말하지 않으면 그것도 조용한 fail-open 이다.**

`gardevoir` 확장에 `inspected` 를 넣는다 — 실제로 돌린 체크포인트 목록이다.

```json
{ "gardevoir": { "action": "allow", "inspected": ["input"], ... } }
```

비스트리밍은 `["input", "output"]`(계획에 있는 것만), 스트리밍은 `["input"]` 이다.
계약에 필드를 더하는 것은 되돌리기 어려우므로(§7) 최소로 넣는다 — 목록 하나면
Phase 3/4 가 항목을 늘릴 때 형태가 바뀌지 않는다.

감사 로그에도 남기고, 출력 프로그램이 있는데 건너뛴 경우 WARNING 을 찍는다.

### 결정 3. 계획이 없으면 통과시키고 감사에 남긴다

키가 지정한 가드레일에 발행본이 없으면 `registry.get()` 이 `None` 이다.

fail-closed 로 하면 발행되지 않은 가드레일 하나가 앱 전체를 세운다. 운영자는
가드레일을 아예 떼는 쪽으로 움직일 것이므로 안전이 오히려 줄어든다.

통과시키되 **보이게** 한다: `guardrail_version=0`(`UNVERSIONED_GUARDRAIL`,
이미 "컴파일된 가드레일 없음"을 뜻한다), `inspected: []`, WARNING 로그, 감사 1행.

### 결정 4. 입력 텍스트는 user 메시지 전체를 이어붙인다

`messages` 는 매 턴 전체가 다시 온다 (§7.4). 마지막 user 메시지만 보면 여러 턴에
나눠 심은 것을 놓친다.

- `role == "user"` 인 항목의 `content` 를 개행으로 이어붙인다.
- `content` 가 리스트(멀티모달)면 `type == "text"` 인 조각만 모은다.
- system/assistant/tool 은 ① 이 아니다 — ②(Phase 3)와 ③이 다룬다.

### 결정 5. 판정 순서 — 입력이 막히면 업스트림을 부르지 않는다

차단할 요청에 토큰을 쓸 이유가 없고, 프롬프트 인젝션을 업스트림에 보내지 않는 것이
그 자체로 방어다.

## File Structure

```
backend/gateway/src/gateway/
  application/inspection/__init__.py
  application/inspection/text.py          extract_input_text / extract_output_texts
  application/inspection/outcome.py       Inspection (결과 DTO)
  application/inspection/inspector.py     Inspector — 계획 잡기, 검사, 마스킹
  application/service/proxy_service.py    (수정) 체크포인트 배선
  application/plan/compiler.py            (수정) MASK 위치 가능성 검증
  domain/exception/guardrail_error.py     (수정) GUARDRAIL-014
  contract.py                             (수정) inspected, blocked 본문 빌더
  composition.py                          (수정) Inspector 주입
tests/
  test_inspection_text.py  test_inspector.py  test_proxy_inspection.py
  test_compiler.py (추가)   test_chat_completions.py (추가)
```

`application/inspection/` 을 `plan/` 과 분리하는 이유: `plan/` 은 그래프를 모르는
순수 변환이고, `inspection/` 은 **OpenAI 페이로드 모양**을 안다. 섞으면 컴파일러가
와이어 포맷에 묶인다.

---

## Task 1: 텍스트 추출

**Files:** `application/inspection/text.py`

**Produces:**
- `extract_input_text(payload: dict) -> str`
- `extract_output_texts(body: dict) -> list[tuple[int, str]]` — `(choice_index, text)`

- [x] Step 1~4: 테스트 → 실패 확인 → 구현 → 커밋

테스트 성질:
1. `test_a_single_user_message` / `test_many_user_messages_are_joined`
2. `test_system_and_assistant_are_not_input` — ①의 정의
3. `test_multimodal_text_parts_are_collected`
4. `test_image_parts_are_ignored`
5. `test_a_missing_messages_key_yields_empty` — 업스트림이 거부할 것을 우리가 먼저
   터뜨리지 않는다
6. `test_a_non_list_messages_yields_empty`
7. `test_a_non_dict_message_is_skipped`
8. `test_null_content_is_skipped`
9. `test_output_texts_carry_the_choice_index` — 마스킹이 그 자리에 되써야 한다
10. `test_output_ignores_a_choice_without_content`
11. `test_output_reads_tool_call_free_messages_only` — ④는 Phase 3
12. `test_extraction_does_not_mutate_the_payload`

---

## Task 2: MASK 위치 가능성 검증 (컴파일러)

**Files:** `application/plan/compiler.py`, `domain/exception/guardrail_error.py`

**Produces:**
- `GuardrailError.UNMASKABLE = ("GUARDRAIL-014", ..., ValidationError)`
- 컴파일 시 MASK 판정의 조상 검사가 전부 `extract` 를 직접 읽는 regex 인지 확인
- `Program.patterns_by_slot: dict[int, object]` — 마스킹용 개별 컴파일 패턴

- [x] Step 1~4

테스트 성질:
1. `test_a_mask_verdict_on_a_direct_regex_compiles`
2. `test_a_mask_verdict_behind_a_transform_is_rejected` — `GUARDRAIL-014`
3. `test_a_mask_verdict_on_a_length_check_is_rejected` — length 는 위치가 없다
4. `test_a_block_verdict_behind_a_transform_still_compiles` — 제한은 MASK 만
5. `test_patterns_by_slot_covers_every_regex_slot`
6. `test_patterns_by_slot_is_empty_without_regexes`
7. `test_the_restriction_names_the_verdict` — `details.node_id`

---

## Task 3: Inspector

**Files:** `application/inspection/outcome.py`, `application/inspection/inspector.py`

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class Inspection:
    action: Action                 # allow / blocked (mask 는 아래 masked_text 로)
    checks_fired: tuple[str, ...]
    pending_model: tuple[str, ...]
    inspected: tuple[str, ...]
    guardrail_version: int
    masked: bool

class Inspector:
    def __init__(self, *, plans: PlanRegistry) -> None
    def plan_for(self, guardrail: str) -> ExecutionPlan | None   # 요청 시작에 1회
    def input(self, plan, payload: dict, *, mode: Mode) -> Inspection
    def output(self, plan, body: dict, *, mode: Mode) -> Inspection  # body 를 제자리 수정
```

`plan_for` 를 분리하는 이유: 요청 하나가 계획을 **한 번** 잡아 입력·출력에 같은 것을
써야 한다 (§6).

`mode` 가 `dry-run` 이면 `collect_all=True` 로 돌리고 `action` 은 항상 allow 로
두되 `would_have` 를 만들 재료를 남긴다.

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_no_plan_inspects_nothing` — `inspected == ()`, version 0
2. `test_a_clean_input_is_allowed`
3. `test_a_dirty_input_is_blocked`
4. `test_input_only_plan_reports_input_inspected`
5. `test_output_masking_replaces_the_span`
6. `test_masking_keeps_the_rest_of_the_text`
7. `test_masking_applies_to_every_choice`
8. `test_masking_reports_masked_true`
9. `test_a_mask_that_matches_nothing_does_not_claim_masked` — fail-open 방지
10. `test_block_beats_mask_on_output`
11. `test_dry_run_never_blocks`
12. `test_dry_run_collects_every_check`
13. `test_dry_run_does_not_mask` — 시험 중에 응답을 바꾸면 시험이 아니다
14. `test_pending_model_is_carried` — Phase 4 가 받을 자리
15. `test_the_same_plan_is_used_for_input_and_output`

---

## Task 4: 프록시 배선 (비스트리밍)

**Files:** `proxy_service.py`, `contract.py`, `composition.py`

**Produces:**
- `contract.blocked_input_body(...)` → §7.3 의 400 본문 (`error.code = content_filter`)
- `contract.blocked_output_body(...)` → `finish_reason = content_filter` + 사유 content
- `build_extension(..., inspected=...)`
- `ProxyService.complete` 가 ① → 업스트림 → ③ 순으로 돈다

**차단 응답의 `content` 에 사유를 넣는 것이 필수다** — 많은 앱이 `finish_reason` 을
보지 않고 `content` 만 쓴다 (§7.3).

- [x] Step 1~5: 테스트 → 실패 확인 → 구현 → 실제 기동 → 커밋 → 돌연변이

테스트 성질:
1. `test_a_blocked_input_never_calls_upstream` — 호출 수 0
2. `test_a_blocked_input_is_400_with_content_filter`
3. `test_the_blocked_body_explains_itself_in_content`
4. `test_a_blocked_output_is_200_with_content_filter`
5. `test_a_blocked_output_replaces_the_content`
6. `test_a_masked_output_keeps_status_200`
7. `test_the_extension_reports_the_guardrail_version`
8. `test_the_extension_reports_inspected_checkpoints`
9. `test_headers_report_the_action`
10. `test_dry_run_returns_the_upstream_body_unchanged`
11. `test_dry_run_reports_would_have`
12. `test_an_allowed_request_is_unchanged_apart_from_the_extension`
13. `test_audit_records_the_checkpoint_and_checks`
14. `test_audit_records_the_guardrail_version`
15. `test_latency_excludes_the_upstream_wait` — 1c 의 성질 유지
16. `test_a_guardrail_without_a_plan_passes_through`

---

## Task 5: 스트리밍

**Files:** `proxy_service.py`

- ① 은 스트림에서도 돈다 (업스트림을 열기 전에 본문이 있다)
- ③ 은 돌지 않는다. `inspected` 에서 빠지고, 출력 프로그램이 있으면 WARNING

- [x] Step 1~4

테스트 성질:
1. `test_a_blocked_input_never_opens_the_stream`
2. `test_a_blocked_input_on_a_stream_is_400` — 스트림을 열지 않았으므로 JSON 이다
3. `test_a_stream_reports_only_input_inspected`
4. `test_a_stream_warns_when_an_output_program_is_skipped` — caplog
5. `test_a_stream_still_appends_the_extension_chunk`
6. `test_stream_audit_records_the_input_verdict`
7. `test_the_openai_sdk_still_parses_the_stream` — §11.9 회귀

---

## Task 6: 감사 + 실제 기동

**Files:** `proxy_service.py`, `infrastructure/audit/clickhouse_sink.py` (확인만)

- `checkpoint`, `checks_fired`, `verdicts`, `guardrail_version`, `tier_reached` 를
  실제 값으로 채운다. Phase 1 은 전부 비어 있었다.
- `tier_reached` = `"rules"` (Phase 4 가 `"model"` 을 더한다)

- [x] Step 1~4: 테스트 → 구현 → 실제 기동(uvicorn + Postgres + ClickHouse) → 커밋

테스트 성질:
1. `test_audit_row_lands_in_clickhouse_with_checks` — 실제 ClickHouse
2. `test_checks_fired_is_queryable` — `Array(LowCardinality(String))` 조회
3. `test_a_blocked_request_is_audited_as_blocked`
4. `test_dry_run_audit_records_the_would_have_action`

---

## Self-Review

**1. 계획 단계에서 고친 것**

- 처음에 MASK 를 그냥 구현하려 했다. 실행기가 위치를 모른다는 것을 뒤늦게 봤고,
  transform 뒤의 패턴을 원본에 다시 돌리면 조용히 아무것도 가리지 않는다는 데
  이르렀다 → 컴파일 시점 거부(`GUARDRAIL-014`).
- 스트리밍에서 출력 검사를 그냥 건너뛰려 했다. 그러면 호출자가 검사된 줄 안다 →
  `inspected` 를 계약에 넣는다.
- 계획이 없을 때 fail-closed 를 고민했다. 발행 안 된 가드레일 하나가 앱을 세우면
  운영자가 가드레일을 떼게 되므로 안전이 줄어든다 → 통과 + 보이게.

**2. 위험**

- `inspected` 는 계약 추가다. 되돌리기 어렵다(§7). 목록 하나로 두어 Phase 3/4 가
  항목만 늘리게 했다.
- 마스킹이 본문을 제자리 수정한다. 원본 바이트를 중계하는 1c 의 성질이 깨지는
  자리이므로, 판정이 없으면 **원본 그대로** 나가는지 테스트로 고정한다.
- ① 이 user 메시지 전체를 이어붙이므로 긴 대화에서 텍스트가 커진다. regex 는
  선형이고 §11 예산 안이지만, 실측을 성능 테스트에 추가한다.
