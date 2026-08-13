# 스트리밍 — 홀드백 + 슬라이딩 윈도우 + 스트리밍 ③④ (Phase 4a)

설계 문서: §9(스트리밍 전체), §7.3(응답 형태), §11.9(SDK 관용성), §10.
선행: Phase 3b — 머지됨.
후속: Phase 4b(모델 티어 — Ollama 가 이 머신에 없어 순서를 뒤로 미뤘다).

## 이 단계가 닫는 것

2c 부터 스트리밍은 ③ 을 검사하지 않았고 3b 부터 ④ 도 검사하지 않았다. 지금은
`inspected` 에서 빠지고 WARNING 이 찍힌다 — 보이기는 하지만 **대부분의 챗봇이
스트리밍이므로 실질적으로 차별화 기능이 꺼진 상태다.**

§9 는 두 장치로 이것을 푼다.

```
생성:   "주민번호는 900101-"  "1234567 입니다"
청크별 검사:  A 에 패턴 없음. B 에 패턴 없음. → 놓침
```

**① 겹치는 슬라이딩 윈도우** — 검사 대상 = 직전 K자 + 새 청크. 경계에 걸친 매치를
놓치지 않고, 누적 전체를 매번 스캔하는 O(n²) 도 피한다.

**② 홀드백** — 항상 마지막 N자를 손에 쥔다. 위험 패턴이 완성되는 순간 그 부분은 아직
방출 전이므로, 치환하고 계속 흘린다. 사용자가 아직 안 봤으니 "사후 수정"이 아니다.

**③ tool_call 버퍼링은 공짜다** — 앱은 조각난 tool_call 로 아무것도 할 수 없어 어차피
다 모일 때까지 기다린다. 프록시가 붙들고 있어도 UX 손실이 0 이다.

## Global Constraints

- 요청 경로다. Pydantic 금지, `orjson`, `re2`.
- **업스트림 청크를 우리가 이해하지 못해도 중계한다.** 프록시가 SSE 파서 때문에
  응답을 잃으면 가드레일이 가용성 문제가 된다.
- **SDK 가 그대로 파싱해야 한다** (§11.9). 커스텀 `finish_reason` 금지, 확장은
  `gardevoir` 객체로. openai SDK 회귀 테스트를 유지한다.
- 감사는 소비자가 터져도 남아야 한다 (1c 에서 확립한 컨텍스트 매니저 `finally`).

## 계획 단계에서 확정한 결정

### 결정 1. 홀드백 단위는 **문자**다

§9 는 "홀드백 32토큰"과 "마지막 N자"를 섞어 쓴다. 우리에게 토크나이저가 없으므로
셀 수 있는 것은 문자뿐이다. 설정을 `stream_holdback_chars` 로 두고 기본 128 을 쓴다.

토큰 환산은 언어에 따라 다르다 — 영어 ~4자/토큰이면 32토큰, 한국어면 더 적은 토큰
수에 해당해 더 보수적이다(지연이 늘고 탐지는 좋아진다). §9 의 시간 예산 논리(32토큰 /
50 tok/s = 640 ms)는 영어 기준임을 문서에 적는다.

기존 설정 이름 `stream_holdback_tokens` 를 바꾼다. 아직 아무도 읽지 않는 값이다.

### 결정 2. 홀드백 0 이면 마스킹이 성립하지 않는다 — 그 사실을 보이게 한다

§9 가 "홀드백 0 = 즉시 방출, 사후 검출(Post 패턴)"이라고 한다. 이미 방출한 구간은
되돌릴 수 없다.

따라서 마스킹 판정이 **이미 방출된 구간**에서 걸리면 가릴 수 없다. 스트림을 멈춰도
사용자가 이미 본 것은 지워지지 않으므로 멈추지 않고, **감사에 "가리지 못했다"를
남기고 WARNING 을 찍는다.** 3a 의 `masked=True` 거짓 보고 방지와 같은 방침이다.

### 결정 3. 멈추는 것은 BLOCK 뿐이고, 이유를 붙인다

§9 의 표대로다.

| 어디서 판정되나 | 멈춤? |
|---|---|
| ① 입력 / ② tool_result | 시작 안 함 (이미 2c·3a) |
| ④ tool_call (조각 버퍼링은 공짜) | 안 멈춤 — 아무것도 방출하지 않았다 |
| ③ MASK, 홀드백 안 | 안 멈춤 — 치환하고 계속 |
| ③ BLOCK | ✅ 멈춤 |

멈출 때 §9 의 형태를 그대로 쓴다: 이유를 담은 content 델타 → `finish_reason:
content_filter` → `gardevoir` 확장. **이유를 붙이는 것이 필수다** — 많은 앱이
`finish_reason` 을 보지 않는다 (§7.3).

### 결정 4. 재방출은 첫 청크를 틀로 삼아 합성한다

홀드백은 본질적으로 내용을 늦추므로 업스트림 청크를 그대로 흘릴 수 없다. 대신:

- **내용이 아닌 청크**(role 만 있는 첫 청크, `finish_reason`, `usage`)는 그대로 중계
- **content 델타**는 버퍼에 모으고, 방출할 때 첫 청크를 틀로 합성

SSE 소비자는 델타를 이어붙이므로 청크 경계가 달라져도 결과가 같다. 그래도 **openai
SDK 로 실제 파싱을 확인한다** (§11.9 회귀).

### 결정 5. 검사 시점은 "새 내용이 도착할 때"다

청크마다 윈도우 검사를 돌린다. §11 실측으로 실행이 0.01~0.27 ms 이므로 청크당 한 번은
생성 속도(50 tok/s = 20 ms/토큰) 대비 무해하다. 성능 테스트로 회귀를 감시한다.

## File Structure

```
backend/gateway/src/gateway/
  application/streaming/__init__.py
  application/streaming/sse.py          SSE 프레임 파싱·직렬화
  application/streaming/accumulator.py  content·tool_calls 누적
  application/streaming/holdback.py     홀드백 + 슬라이딩 윈도우 방출기
  application/service/proxy_service.py  (수정) 스트리밍 ③④ 배선
  settings.py                           (수정) stream_holdback_chars, stream_window_chars
tests/
  test_sse.py  test_accumulator.py  test_holdback.py
  test_proxy_streaming.py  test_plan_performance.py(추가)
```

`application/streaming/` 을 분리하는 이유: `inspection/` 은 완성된 페이로드를 보고,
여기는 **조각을 다룬다**. 섞으면 검사기가 SSE 를 알게 된다.

---

## Task 1: SSE 코덱

**Files:** `application/streaming/sse.py`

**Produces:**
- `parse_frames(raw: bytes) -> tuple[list[Frame], bytes]` — 완성된 프레임과 남은 꼬리
- `Frame` — `data: bytes`, `payload: dict | None`(파싱 실패면 None), `is_done: bool`
- `render(payload: dict) -> bytes`, `render_done() -> bytes`

- [ ] Step 1~4: 테스트 → 실패 확인 → 구현 → 커밋

테스트 성질:
1. `test_one_frame` / `test_many_frames_in_one_read`
2. `test_a_frame_split_across_reads_is_buffered` — TCP 는 경계를 지켜주지 않는다
3. `test_the_done_sentinel_is_recognised` — `data: [DONE]`
4. `test_a_non_json_frame_is_kept_verbatim` — 우리가 이해 못해도 중계한다
5. `test_a_comment_frame_is_kept` — `: keep-alive`
6. `test_crlf_line_endings` — 구현체마다 다르다
7. `test_render_round_trips`
8. `test_an_empty_read_yields_nothing`
9. `test_the_tail_is_returned_for_the_next_read`

---

## Task 2: 누적기

**Files:** `application/streaming/accumulator.py`

**Produces:**
- `Accumulator.feed(payload) -> str` — 새로 도착한 content 조각
- `Accumulator.tool_calls -> list[dict]` — 완성 형태로 재조립
- `Accumulator.template` — 합성에 쓸 첫 청크의 틀
- `Accumulator.finish_reason`, `.trailing` — 그대로 중계할 것들

- [ ] Step 1~4

테스트 성질:
1. `test_content_deltas_accumulate`
2. `test_a_role_only_first_chunk_becomes_the_template`
3. `test_tool_call_arguments_are_joined_by_index` — §9 의 예시
4. `test_tool_call_name_and_id_come_from_the_first_fragment`
5. `test_two_tool_calls_accumulate_independently`
6. `test_the_finish_reason_is_captured`
7. `test_usage_is_captured` — 감사에 토큰 수가 필요하다
8. `test_a_chunk_without_choices_is_ignored`
9. `test_a_malformed_delta_is_ignored`
10. `test_the_accumulated_tool_calls_match_the_non_streaming_shape` — ④ 검사기가
    같은 코드를 쓰므로 형태가 같아야 한다

---

## Task 3: 홀드백 방출기

**Files:** `application/streaming/holdback.py`

**Produces:**
- `Holdback(chars: int, window: int)`
- `.offer(text) -> str` — 방출할 부분 (마지막 `chars` 자는 남긴다)
- `.window() -> tuple[str, int]` — 검사 대상과 그 시작 오프셋
- `.mask(start, end, placeholder) -> bool` — 아직 방출 안 된 구간이면 치환하고 True
- `.flush() -> str` — 스트림 끝에 남은 것

- [ ] Step 1~5: 테스트 → 실패 확인 → 구현 → 커밋 → 돌연변이

테스트 성질:
1. `test_nothing_is_emitted_until_the_holdback_is_full`
2. `test_the_tail_is_always_held`
3. `test_flush_releases_the_tail`
4. `test_zero_holdback_emits_immediately` — §9 의 Post 패턴
5. `test_the_window_covers_the_chunk_boundary` — "900101-" + "1234567"
6. `test_the_window_is_bounded` — 누적 전체를 스캔하지 않는다 (O(n²) 방지)
7. `test_masking_inside_the_holdback_succeeds`
8. `test_masking_an_already_emitted_span_fails` — 되돌릴 수 없다
9. `test_masking_changes_what_is_emitted_next`
10. `test_emitted_text_is_never_re_emitted`
11. `test_the_total_emitted_equals_the_input_when_nothing_masks`
12. `test_masking_shrinks_or_grows_the_output_consistently`

---

## Task 4: 스트리밍 ④ (tool_call)

**Files:** `application/service/proxy_service.py`

- 조각을 전부 버퍼링한다 (§9: 공짜)
- 완성되면 ④ 검사 — 비스트리밍과 **같은 검사기**를 쓴다
- 통과하면 버퍼를 그대로 방출, 막히면 §9 형태의 차단 프레임
- `inspected` 에 `tool_call` 추가, WARNING 제거

- [ ] Step 1~5: 테스트 → 실패 확인 → 구현 → 실제 기동 → 커밋 → 돌연변이

테스트 성질:
1. `test_a_streamed_tool_call_is_inspected`
2. `test_a_blocked_streamed_tool_call_emits_no_tool_calls`
3. `test_a_blocked_streamed_tool_call_uses_content_filter`
4. `test_an_allowed_streamed_tool_call_is_relayed_intact`
5. `test_arguments_split_across_chunks_are_joined` — §9 의 예시 그대로
6. `test_the_extension_reports_tool_call_inspected`
7. `test_no_warning_when_tool_call_is_inspected`
8. `test_the_openai_sdk_parses_a_streamed_tool_call` — §11.9

---

## Task 5: 스트리밍 ③ (홀드백 안의 텍스트 검사)

**Files:** `application/service/proxy_service.py`

- 청크마다 윈도우 검사
- MASK: 홀드백 안이면 치환하고 계속, 밖이면 못 가림 + WARNING + 감사
- BLOCK: §9 형태로 중단
- `inspected` 에 `output` 추가

- [ ] Step 1~5

테스트 성질:
1. `test_a_pattern_spanning_two_chunks_is_caught` — **§9 의 핵심 문제**
2. `test_masking_inside_the_holdback_does_not_stop_the_stream`
3. `test_the_masked_stream_never_emits_the_original`
4. `test_a_block_stops_the_stream_with_a_reason`
5. `test_the_stop_uses_a_standard_finish_reason`
6. `test_the_stop_appends_the_extension`
7. `test_zero_holdback_cannot_mask_and_says_so` — 감사 + WARNING
8. `test_a_clean_stream_is_relayed_unchanged`
9. `test_the_openai_sdk_parses_a_masked_stream` — §11.9
10. `test_audit_records_the_streaming_verdict`
11. `test_audit_survives_a_consumer_that_disconnects` — 1c 의 성질

---

## Task 6: 실측 + 문서

- 청크당 검사 비용, 홀드백이 만드는 지연, 윈도우 크기 대비 탐지
- §9 에 실측값, §11 에 스트리밍 항목 추가
- `inspected` 가 스트리밍에서도 네 체크포인트를 다 담을 수 있게 됐음을 §14 에 반영

- [ ] Step 1~3

---

## Self-Review

**1. 계획 단계에서 고친 것**

- 홀드백을 토큰 단위로 두려 했다. 토크나이저가 없으므로 셀 수 있는 것은 문자다 →
  설정을 문자로 바꾸고 §9 의 토큰 논리가 영어 기준임을 적는다.
- 마스킹이 항상 가능하다고 가정했다. 홀드백 0 이면 이미 방출한 구간을 되돌릴 수 없다 →
  못 가렸으면 그 사실을 감사와 로그에 남긴다.
- 업스트림 청크를 그대로 흘리려 했다. 홀드백이 내용을 늦추므로 불가능하다 → 첫 청크를
  틀로 합성하고, SDK 가 실제로 파싱하는지 §11.9 회귀로 확인한다.
- ④ 를 ③ 과 같은 루프에서 처리하려 했다. ④ 는 **전부 버퍼링**(공짜)이고 ③ 은
  **흘리면서 검사**다. 성질이 반대라 방출기를 나눈다.

**2. 위험**

- SSE 파싱은 업스트림 구현체마다 다르다(CRLF, 주석 프레임, 청크 경계). 이해 못한
  프레임은 그대로 중계하고, 그 성질을 테스트로 고정한다.
- 청크 경계를 바꾸므로 SDK 호환이 깨질 수 있다. §11.9 가 이미 회귀 테스트로 있으니
  스트리밍 판본을 추가한다.
- 홀드백이 지연을 만든다. 기본 128자는 생성 속도 50 tok/s·영어 기준 ~640 ms 다.
  체감이 문제면 설정으로 줄이되, 0 이면 마스킹이 안 된다는 것을 문서에 적는다.

**3. 열어두는 것**

- 모델 티어(§4 의 힌트형/모델형)는 4b. 홀드백이 만든 시간 예산 안에서 모델을 부르는
  것이 §9 의 논리이므로, 4b 가 이 방출기 위에 얹힌다.
- AWS 의 Dynamic Buffer(250→500→1000단어)는 차용하지 않는다 (§9).
