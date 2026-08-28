# ④ tool_call 노드 재설계 — 특수 노드를 걷어내고 Extract·Check 문법으로

- 작성일: 2026-08-28 (KST)
- 상태: 설계 확정(논의 결과). 구현 미착수.
- 근거: 설계 문서 §5(노드 역할)·§7.6(미등록 툴)·§8(액션 통제)·§10(감사), phase4 스펙.

## 1. 문제

④ tool_call 은 나머지 체크포인트와 **다른 문법**을 쓴다.

- ①②③: `extract`(무엇을 볼지) → `regex`/`model`(어떻게 볼지) → `verdict`(결론)
- ④: `taint` / `side_effect` / `provenance` 세 **특수 노드**가 각자 boolean 을 내고 verdict 로 간다

이 셋은 **아무 입력도 읽지 않는다**(arity `(0,0)`). "Check 인데 소스"인 이질적 형태다. 그리고 결정적으로:

**④ 의 `Subject` 에는 `text` 가 없다.**
```python
input:       Subject(text=…, tainted=…)
tool_result: Subject(text=…, tainted=…)
output:      Subject(text=…, tainted=…)
tool_call:   Subject(tainted=…, tool_name=…, foreign_args=…)   ← text 없음
```
즉 **인수 내용을 검사할 방법이 아예 없다.** `"send_email 의 body 에 주민번호가 있으면 차단"` 같은,
가장 흔하고 중요한 정책이 표현 불가능하다. LLM 이 툴로 PII 를 밖으로 내보내는 경로가 열려 있다.

### 왜 특수 노드가 생겼나
`extract` 가 **checkpoint 하나만** 받는데 그게 두 가지를 동시에 뜻하기 때문이다:
```python
case Extract():
    slots[out] = text      # text = subject.text — "지금 실행 중인 체크포인트"가 결정
```
**"언제 평가되는가(at)"와 "무엇을 읽는가(from)"가 융합**돼 있다. 그래서 "④ 시점에 툴 결과 이력을 보는"
표현이 불가능했고, 그 자리를 `taint` 가 특수 노드로 메웠다. 원리적 제약이 아니라 **구현의 인공물**이다.

## 2. 결정

### 2.1 제거
- **`NodeType.TAINT`** — 능력은 `extract(from: tool_result, at: tool_call)` 로 보존(§2.2)
- **`NodeType.SIDE_EFFECT`** — `tool_extract` 의 **선택자**로 흡수
- **`NodeType.PROVENANCE`** — 제거. 대체 수단은 §5

### 2.2 Extract 의 두 축 분리
```
extract(from, at)
  from: user_text | tool_result | trusted_text | output_text
  at:   input | tool_result | output | tool_call
```
- `at` 은 이 노드가 **어느 체크포인트 프로그램에 속하는지**(부분 그래프의 뿌리). 지금 `checkpoint` 의 역할.
- `from` 은 **무엇을 슬롯에 넣는지**. 기존 동작은 `from == at` 인 경우와 같다(하위 호환).
- 이로써 `extract(from: tool_result, at: tool_call) → regex(".")` 가 **기존 `taint` 와 같은 뜻**이 된다.

### 2.3 신규: `tool_extract`
```
tool_extract(
  tools:  { exclude: [...] }        # 기본. 목록에 없는 툴 = 선택됨(§7.6 fail-safe)
        | { include: [...] }
  field:  name                      # 툴 이름
        | arguments                 # 인수의 문자열 값들을 이어붙인 것
        | "<path>"                  # 특정 경로. 예: "to", "payload.meta.id", "cc[*]"
)
```
- `at` 은 `tool_call` 고정(다른 체크포인트엔 평가할 호출이 없다 — 현재 `WRONG_CHECKPOINT` 규칙 유지).
- **경로 문법은 이미 구현돼 있다.** `argument_strings()` 가 `(경로, 값)` 을 낸다 — 실측:
  ```
  'to'                = 'a@b.com'
  'cc[0]'             = 'x@y.com'
  'payload.subject'   = '안녕'
  'payload.meta.id'   = 'AB-12345'
  ```
  여기에 **`[*]`(배열 전체)만 추가**한다. `cc[*]` 는 `cc[0]`, `cc[1]` … 의 값을 모은다.
- **`field: arguments` 는 값들만 이어붙인다**(키 이름·따옴표·중괄호 제외).
  예: `"a@b.com 안녕 AB-12345"`. 원본 JSON 문자열을 그대로 주면 키 이름과 구두점이 섞여 regex 가
  지저분해지고 오탐이 는다.
- 경로가 없거나 값이 문자열이 아니면 **빈 문자열**. (숫자·불리언은 대상 아님 — 현재 `_walk` 와 동일)

### 2.4 신규: `NOT`
단항 논리 노드. 슬롯 하나를 읽어 부정한다. 3-상태를 지킨다:
```
True → False,  False → True,  PENDING → PENDING
```
`"사내 도메인이 아니면 차단"` 처럼 **부정 조건**이 allowlist 정책의 핵심이라 필요하다.
(지금은 `side_effect` 가 "목록에 없으면 참"으로 부정을 노드 안에 감춰두고 있었다.)

### 2.5 선택되지 않은 호출
`tools` 선택자에 걸리지 않은 호출은 **그 호출에 대해 프로그램을 돌리지 않는다**(통과).
"선택자"의 의미가 그것이고, 이래야 `tool_extract(exclude=[read_file]) → regex(".") → verdict(block)`
가 현재 `side_effect` 와 정확히 같은 정책이 된다.

### 2.6 여러 호출 (현행 유지)
응답에 tool_call 이 여러 개면 **호출마다 프로그램을 돌리고, 하나라도 걸리면 응답 전체를 차단**한다.
§8 근거: 하나만 빼고 넘기면 모델의 계획이 반쯤 실행되고, 앱이 남은 툴을 불러 그 결과로 다시 요청한다.

## 3. 안전 기본값 (§7.6 유지 — 절대 뒤집지 말 것)
- `tools` 기본은 **`exclude`**. `include` 만 지원하면 **새로 추가된 툴이 검사에서 빠져 fail-open** 이 된다.
- 툴 이름을 못 읽으면(`tool_name()` 이 빈 문자열) **선택된 것으로 취급**한다.
- 인수 JSON 파싱 실패는 값 없음으로 보되(가용성 우선, 현행 동작), **감사에 그 사실을 남긴다**.
  지금은 조용히 `[]` 를 반환해 파싱 실패가 보이지 않는다 — 이건 개선한다.

## 4. §8 정책이 어떻게 표현되는가

### 4.1 기존 정책의 이전 (능력 손실 없음)
```
[before] taint → ┐
                 ├ verdict(combine=all, block)      "외부 데이터 읽은 뒤 부작용 툴"
     side_effect ┘

[after]  extract(from: tool_result, at: tool_call) → regex(".") ─┐
                                                                  ├ verdict(all, block)
         tool_extract(exclude=[read_file, search], field: name) → regex(".") ─┘
```

### 4.2 지금은 불가능하지만 새로 가능해지는 정책 (이게 목적이다)
```
# 사내 도메인이 아닌 주소로 메일 → 차단
tool_extract(exclude=[read_file], field: "to") → regex("@company\.com$") → NOT → verdict(block)

# 인수 어디에든 주민번호 → 차단
tool_extract(field: arguments) → regex("\d{6}-\d{7}") → verdict(block)

# 특정 툴만 차단
tool_extract(include=["delete_files"], field: name) → regex(".") → verdict(block)

# 본문에 자연어 정책 (모델 티어)
tool_extract(field: "payload.body") → model("기밀 정보가 포함됐는가") → verdict(block)

# 위험 경로 접근
tool_extract(include=["read_file"], field: "path") → regex("^/etc/") → verdict(block)
```

## 5. `provenance` 를 뺀 자리
`provenance` 는 **런타임 값 대 런타임 값 비교**라 일반 Check(고정 설정 → 슬롯 하나)로 표현되지 않는다.
제거하면 `"인수 값이 툴 결과에서 왔다"` 판정이 사라진다. 대체 수단:

1. **allowlist regex**(권장) — `field: "to"` 에 사내 도메인 패턴 + `NOT`. 열거 가능한 값이면 이쪽이 더 강하다
   (공격자가 사내 도메인을 쓸 수 없다).
2. **승인 흐름**(Phase 6, 미구현) — 넓은 조건에서 `approval_required`. §8 이 "실무의 정답"이라 한 것.
3. 열거 불가능한 값(임의 URL·경로)에 정확도가 필요해지면, 그때 **이항 Check**(`contains(A, B)`)를 별도로
   도입한다. 이번 범위 아님.

`foreign_arguments()`/`argument_strings()` 구현은 남겨둔다 — `argument_strings` 는 `tool_extract` 가 쓴다.

## 6. 실행기·컴파일러 영향
- `Subject` 에 ④ 용 텍스트가 생긴다. 호출마다 `tool_extract` 의 `field` 로 뽑은 문자열을 넣는다.
  `tool_name`/`foreign_args` 필드는 `provenance`/`side_effect` 제거와 함께 정리한다.
- 명령: `Taint`/`SideEffect`/`Provenance` 삭제, `ToolExtract`(선택자+field)·`Not` 추가.
  `Extract` 에 `from` 추가.
- 컴파일러의 `SOURCE_TYPES` 는 `EXTRACT`, `TOOL_EXTRACT` 만 남는다. 체크포인트 그룹핑은 **`at`** 으로 한다.
- **3-상태(PENDING) 의미를 깨지 말 것.** 규칙-only 경로의 결과·성능(§11.4)은 불변이어야 한다.

## 7. 마이그레이션
실 DB 의 발행본·초안 그래프를 변환한다(현재 `default` 에 `taint`·`side_effect` 가 있다):
- `taint(checkpoint: X)` → `extract(from: tool_result, at: X)` + `regex(".")` 2노드로
- `side_effect(read_only: L, checkpoint: tool_call)` → `tool_extract(exclude: L, field: name)` + `regex(".")`
- `provenance` → **자동 변환 불가**. 존재하면 마이그레이션을 실패시키지 말고, 해당 verdict 를 보수적으로
  유지하되(예: 그 입력을 제거하고 나머지로 평가) **무엇이 바뀌었는지 로그와 문서에 남긴다**.
  실 DB 에 provenance 노드가 있는지 먼저 확인하고 판단할 것.
- 발행본은 불변이지만 **컴파일이 되어야 하므로** 변환 대상이다.

## 8. 감사 (§10 유지)
- 검사에는 인수 **값**을 쓰되, 감사에는 **경로 이름만** 남긴다.
  현재 `evidence = {"tool": name, "arguments": ["to", "payload.meta.id"]}` 형태를 유지·확장한다.
- 인수 값 자체는 감사 본문(`input_body`)에 이미 원문으로 남는다(항상 저장, 접근 통제).

## 9. 콘솔
- 노드 팔레트: `taint`/`side_effect`/`provenance` 제거, `tool_extract` 추가.
  역할 분류는 현재 4역할(Extract / Transform / Check / Verdict)에 그대로 들어간다 —
  `tool_extract` 는 **Extract**, `NOT` 은 **Check**(또는 Logic 소분류).
- `tool_extract` 인스펙터: tools 모드(exclude/include) + 목록, field(name / arguments / 경로 입력).
  경로 입력은 자유 텍스트지만 `to`, `payload.meta.id`, `cc[*]` 예시를 placeholder 로.
- §8 정책은 **템플릿**으로 제공한다(`templates.ts`). 특수 노드가 사라져 저작자가 5~6 노드를 그려야 하므로,
  템플릿에서 시작해 수정하는 흐름이 필요하다. 최소 2개: "오염 후 부작용 툴", "허용 도메인 외 발신 차단".
- 문구는 절제 유지(#83).

## 10. 단계
1. 도메인·실행기·컴파일러(노드 제거/추가, 두 축, PENDING 보존) + 마이그레이션
2. 콘솔(팔레트·인스펙터·템플릿)
3. 문서: 설계 §5·§7.6·§8, `gardevoir-be`/`fe` 스킬

## 11. 비목표
- 이항 Check(`contains`) — provenance 대체가 필요해질 때 별도 판단
- 승인 흐름(`approval_required`) — Phase 6
- ImageExtract — 모델 티어가 별도 경로로 이미지를 다루므로(#88) 지금은 불필요
