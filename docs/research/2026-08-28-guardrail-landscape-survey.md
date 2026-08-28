# LLM 가드레일 지형 조사

- 조사일: 2026-08-28
- 대상: NeMo Guardrails, Guardrails AI, OpenAI Guardrails Python, Llama Guard 4,
  Granite Guardian, Presidio, Promptfoo, garak
- 비교 기준: [gardevoir 설계문서](../superpowers/specs/2026-08-12-gardevoir-design.md)
  §3, §4, §8, §9, §10
- 범위: 공식 문서·공식 저장소·공식 모델카드에 공개된 내용과 기존 gardevoir 실측만 사용

## 결론

gardevoir의 가장 차별적인 부분은 입력·도구 결과·모델 출력·도구 호출의 네 지점에 동일한
정책을 적용하고, 도구 호출을 콘텐츠가 아니라 **실행 권한**으로 본다는 점이다. 조사 대상 중
이 네 지점을 한 프록시 계약으로 묶고, 정책별 도구 이름·인자 제한과 대화 오염(taint)을 함께
적용한다고 문서화한 제품은 없었다. NeMo IORails는 로컬 allowlist와 JSON Schema 검증으로
구조 검증이 더 강하고, Granite Guardian과 OpenAI Guardrails는 사용자 의도와 호출의 의미적
불일치를 확률적으로 잡지만, 권한·승인·실행 결과의 출처를 보장하지 않는다.

반대로 gardevoir가 분명히 빠뜨린 것은 세 가지다.

1. Retrieval rail: 검색 문서·청크가 모델 프롬프트에 들어가기 전에 신뢰도, ACL, 관련성,
   프롬프트 인젝션, PII를 검사하는 별도 경계가 없다. 현재 ② `tool_result`는 검색이 외부 도구로
   드러난 경우 일부 겹치지만, 검색기 내부에서 선택된 청크와 메타데이터는 보지 못한다.
2. Dialog rail: 여러 턴의 순서, 선행 조건, 반드시 거쳐야 할 확인 단계 같은 상태기계를 강제하지
   않는다. ④ 도구 호출 검사는 한 번의 행동을 통제하지만 업무 흐름 자체를 증명하지 않는다.
3. 공격 회귀검증: Promptfoo와 garak은 모두 gardevoir의 OpenAI 호환 Chat Completions
   엔드포인트를 직접 겨눌 수 있다. 다만 둘 다 기본 사용만으로 §9의 SSE 청크 누출을 검증하지
   못하며, 한국어 품질도 별도 말뭉치로 고정해야 한다.

지연에 관해서는 공개 자료가 예상보다 빈약하다. 범용 프레임워크인 NeMo, Guardrails AI,
Presidio, Promptfoo, garak에는 재현 가능한 제품 전체 p50/p95가 없다. Llama Guard 4와 Granite
Guardian 모델카드도 품질 지표만 공개하고 wall-clock 지연은 공개하지 않는다. OpenAI
Guardrails Python만 특정 LLM 검사와 데이터셋에 대한 TTC p50/p95를 공개한다. gardevoir의
`3.36초`도 모델 티어 일반 성능이 아니라 **동일한 짧은 한국어 문장에서 Qwen 기반 span
localizer를 7회 실행한 값**이므로 일반 SLO나 모든 모델 판정의 대표값으로 쓰면 안 된다.

**[gardevoir 실측 · 2026-08-28 보강]** 이 지적을 받아 실제 **판정** 티어 지연을 측정했다.
배포 중인 `shieldstral-1.0-3b` 에 운영과 같은 형태(`max_tokens=1, temperature=0, logprobs,
top_logprobs=20`)로 warm-up 뒤 7회씩 호출한 결과 —
짧은 한국어 문장(27자) **p50 42.5 ms**(min 40.6 / max 43.2),
약 1,400자 문서 **p50 53.4 ms**(min 52.1 / max 55.2).
즉 **판정 지연은 `3.36초` 가 아니라 수십 ms 수준**이고, `3.36초` 는 자유 생성으로 JSON 을 만들어야
하는 **localizer 경로**의 값이다. 1토큰 분류와 자유 생성은 비용 구조가 다르다.
이 구분을 놓치면 "모델 티어는 비싸니 값싼 게이트 뒤에 둔다" 같은 설계 판단이 잘못된 전제 위에 선다.

즉시 가져올 우선순위는 다음과 같다.

- 낮은 비용: Promptfoo의 정적 한국어 회귀 코퍼스와 CI gate, 도구 호출 JSON Schema 검사,
  정책별 typed placeholder, SSE 누출 전용 테스트.
- 중간 비용: garak의 선별 probe를 야간 실행, Retrieval 컨텍스트를 프록시에 전달하는 선택적
  확장 계약, 안정적 hash 가명화.
- 높은 비용: 가역 암호화 가명화와 키 수명주기, Dialog 상태기계, 승인 토큰·재생 방지·만료·
  감사까지 포함한 사람 승인 흐름.

## 조사 방법과 증거 표기

[출발점 글](https://gasbugs.tistory.com/710)은 도구 목록을 잡는 데만 사용했다. 이 글의 비교표나
주장을 근거로 재인용하지 않았고, 아래 사실은 각 제작사의 공식 문서·저장소·모델카드에서 다시
확인했다.

- **[공식 동작]** 공식 문서·코드·모델카드가 설명한 기능 또는 계약.
- **[제작사 실측]** 제작사가 표본·지표와 함께 공개한 수치. 독립 실측은 아니다.
- **[제작사 주장]** 재현 조건이나 표본이 충분하지 않은 성능 서술.
- **[gardevoir 실측]** 이 저장소의 기존 research에 기록된 로컬 측정.
- **[추정]** 공식 동작으로부터 도출했지만 직접 보장되지는 않은 결론.
- **[판단]** gardevoir에 적용할 때의 설계 판단.
- **확인 필요** 공식 근거가 없거나 현재 자료로 결론을 닫을 수 없는 항목.

라이선스는 법률 자문이 아니다. 코드 저장소의 라이선스와 사용되는 모델 가중치·외부 API의
조건을 분리해 기록했다.

## gardevoir 비교 기준

설계문서에서 읽은 현재 기준은 다음과 같다.

- §3: ① 사용자 입력, ② 도구 결과, ③ 모델 출력, ④ 도구 호출의 네 체크포인트.
- §4: 정규식·키워드 같은 결정적 규칙을 먼저 실행하고, 필요한 경우 확률적 모델 티어로 간다.
  결정적 매처는 span을 내므로 `MASK`가 가능하지만, 모델 판정은 span이 없어서 저작 시점에
  `MASK` 정책을 거부한다.
- §8: 도구 이름·인자 allowlist와 대화 이력의 오염을 근거로 action을 통제한다. 사람 승인이 더
  적합한 경우가 있음을 인정하지만 승인 흐름은 구현하지 않았다.
- §9: 출력 스트림은 128자 holdback과 512자 overlap sliding window로 검사한다. 도구 호출은
  완성된 JSON을 버퍼링한 뒤 검사한다.
- §10: 감사 이벤트는 비동기 큐와 ClickHouse batch로 요청 경로에서 분리한다.

기존 세 조사에서 이어받은 기준도 중요하다.

- **[gardevoir 실측]**
  [sLLM 조사](./2026-08-27-sllm-guardrail-survey.md)의 ShieldGemma/Shieldstral 계열은 짧은
  판정에는 빠를 수 있으나 span을 내지 않는다.
- **[gardevoir 실측]**
  [마스킹 localizer 조사](./2026-08-27-masking-localizer-survey.md)의 Qwen guided-JSON
  localizer는 동일한 짧은 한국어 문장 `n=7`에서 p50 3,361.8ms, p95 3,393.7ms였다. 이는
  localizer 경로의 작은 실험이지 일반적인 “모델 티어 p50”이 아니다. 같은 조사에서
  `gliner_multi`의 외부 한국어 F1은 37.26으로 기록돼 한국어 NER 근거도 약하다.
- **[gardevoir 실측]**
  [문서·이미지 조사](./2026-08-28-document-image-guardrail.md)에서는 Shieldstral이 한국어
  문서 위험을 분류했지만 위치를 주지 못했고, 정책 문맥 혼동도 관찰됐다.

## 1. NeMo Guardrails

### 동작과 판정

**[공식 동작]** NeMo는 애플리케이션과 LLM·검색기·도구 사이에 들어가는 programmable rail
runtime이다. 공식 [rail 분류](https://docs.nvidia.com/nemo/guardrails/latest/about-nemo-guardrails-library/rail-types)는
입력, retrieval, dialog, execution, 출력의 다섯 경계를 구분한다. Colang 흐름·Python action의
결정적 로직, 정규식/PII 엔진, 분류 모델, LLM self-check, 외부 API를 조합할 수 있으므로 제품
자체는 결정적 또는 확률적이라고 한쪽으로 분류할 수 없다.

- Input rail: 주 LLM 호출 전에 검사·정제한다.
- Retrieval rail: 검색된 문서·청크를 모델 컨텍스트에 넣기 전에 검사·변환한다.
- Dialog rail: 여러 턴의 허용 흐름과 다음 동작을 제약한다.
- Execution rail: 도구 호출·인자·결과를 검사한다.
- Output rail: 모델 응답을 차단·수정·검증한다.

### 지연과 비용

**[공식 동작]** 현재
[runtime security FAQ](https://docs.nvidia.com/nemo/guardrails/resources/runtime-security-faq)는
활성 rail, 엔진, 모델 제공자, 네트워크, 길이, 스트리밍, 동시성, 하드웨어에 따라 결과가 달라져
배포 독립적인 p50/p95를 제시하지 않는다. **공개된 범용 제품 실측치는 없다.**

**[제작사 실측, 구버전 구조]** 2023년 공식
[EMNLP demo 논문](https://aclanthology.org/2023.emnlp-demo.40.pdf)은 고전적인 dialog 경로가
사용자 발화를 canonical form으로 바꾸고, 다음 단계와 bot 메시지를 정하는 세 번의 순차적이며
batch 불가능한 LLM 호출을 사용해 vanilla 호출 대비 대략 3배의 지연·비용을 만든다고 설명했다.
이는 현재 모든 NeMo 설정의 수치가 아니라 당시 dialog 구현의 구조적 측정이다.

**[공식 동작]** 지연 완화 수단은 다음과 같다.

- 독립적인 I/O-bound input/output rail을 `parallel: true`로 실행한다. blocking verdict가 나오면
  이후 경로를 중단할 수 있지만, 이미 시작한 병렬 외부 호출 비용이 항상 회수된다는 보장은 없다.
  [병렬·speculative 설정](https://docs.nvidia.com/nemo/guardrails/configure-guardrails/yaml-schema/guardrails-configuration)
- speculative input generation은 input rail과 주 LLM 생성을 겹친다. 안전하면 input 검사 지연을
  숨기지만 차단되면 이미 시작한 생성 비용을 버린다. streaming에서는 순차 경로로 fallback한다.
- [model memory cache](https://docs.nvidia.com/nemo/guardrails/latest/configure-guardrails/caching/model-memory-cache)는
  공백을 정규화한 정확한 prompt match를 SHA-256 key로 저장하는 process-local LFU cache다.
  Content Safety, Topic, Jailbreak의 지원 모델 호출을 생략할 수 있지만 의미적 유사 캐시는 아니다.
- rail별 로컬 모델·외부 API·규칙을 선택할 수 있고, 결정적 규칙을 앞에 두거나 출력 청크 크기를
  키우면 호출 수를 줄일 수 있다. 후자는 탐지·노출 지연과 맞바꾼다.

LLM judge 호출 수는 설정에 따라 달라진다. self-check rail 하나는 해당 검사 지점에서 judge
호출 하나를 더하고, 여러 rail은 직렬 또는 병렬로 호출 비용이 합산된다. Dialog flow는 구성에
따라 여러 번 호출하므로 “요청당 한 번”으로 예산을 잡을 수 없다. 정확한 상한은 실제 Colang
flow와 재시도 정책을 펼쳐 계산해야 한다.

### 스트리밍

**[공식 동작]** [output rail streaming](https://docs.nvidia.com/nemo/guardrails/configure-guardrails/yaml-schema/streaming/output-rail-streaming)은
기본 `chunk_size=200` 토큰, `context_size=50` 토큰 overlap이다.

- `stream_first=true`가 기본이며 청크를 사용자에게 먼저 보낸 뒤 검사한다. 차단하면 JSON 오류로
  스트림을 끝내지만 위반 청크는 이미 노출됐다.
- `stream_first=false`는 청크를 검사한 뒤 통과한 청크만 보낸다. 청크마다 rail 지연을 TTFT와
  중간 출력에 더하지만 선노출은 막는다.
- gardevoir §9와 형태는 비슷하지만 단위가 토큰 대 문자이고, gardevoir는 128자 holdback을
  항상 둔다. NeMo 기본값은 gardevoir보다 누출 위험을 명시적으로 허용한다.

**[공식 동작]** IORails 도구 호출 스트리밍은 조각난 tool-call JSON을 누적하고 완성된 뒤 로컬
검사를 통과해야 최종 청크를 내보낸다. 이는 gardevoir의 ④ 전체 JSON 버퍼링과 같은 방향이다.

### 마스킹과 도구 통제

NeMo PII rail은 Presidio, GLiNER, Private AI 등 선택한 detector가 준 span을 바탕으로 입력·출력·
retrieval 텍스트를 마스킹할 수 있다. 구체적인 가역성·placeholder 규칙은 선택한 detector와 rail
구현에 종속되므로 NeMo 자체가 하나의 가명화 계약을 제공한다고 볼 수 없다.

**[공식 동작]** 최신 [rail engine support 표](https://docs.nvidia.com/nemo/guardrails/reference/rail-engine-support)와
[0.23 release note](https://docs.nvidia.com/nemo/guardrails/latest/about-nemo-guardrails-library/release-notes)는
IORails tool calling이 추가 LLM/API 호출 없이 로컬에서 다음을 검사한다고 명시한다.

- 모델이 내놓은 tool name allowlist와 arguments JSON Schema.
- tool result의 `tool_call_id` 연결, 이름 일치, content 구조.
- fail-closed와 streaming fragment 완성 후 검증.

단, 도구를 실행하지 않고, 결과 내용의 안전성·schema·provenance를 보증하지 않는다. 이 점에서는
gardevoir ②가 더 의미론적이지만, **도구 정의의 JSON Schema를 gardevoir ④에서 강제하는지는
설계문서만으로 확인되지 않는다. 확인 필요.**

### Retrieval·Dialog, 한국어, 라이선스

Retrieval과 Dialog의 의미는 뒤의 별도 절에서 분석한다. 한국어는 프레임워크 차원에서 금지되지
않지만 실제 성능은 선택한 LLM·분류기·PII recognizer에 달린다. 공식 NeMo 전체 한국어 평가나
지원 보장은 찾지 못했다. **한국어 실지원은 확인 필요**이며, 지원 모델의 자체 언어 목록을 따로
검증해야 한다.

- 코드: [Apache-2.0](https://github.com/NVIDIA-NeMo/Guardrails/blob/develop/LICENSE.md).
- 모델 가중치·외부 rail: 각 모델카드와 API 조건이 별도다. Apache 코드가 연결된 NVIDIA/Meta/
  타사 가중치까지 Apache로 바꾸지 않는다.

## 2. Guardrails AI

### 동작과 판정

**[공식 동작]** Guardrails AI의 `Guard`는 LLM 입력·출력 또는 독립적인 값 검증 경계에
[validator](https://guardrailsai.com/guardrails/docs/concepts/validators)를 붙인다. validator는
`PassResult`/`FailResult`와 실패 span을 반환하고, 정규식·schema·Python 규칙이면 결정적이며
NER/분류기/LLM/API를 쓰면 확률적이다. validator package마다 판정 수단과 라이선스가 다르다.

실패 후에는 [OnFailAction](https://guardrailsai.com/guardrails/docs/concepts/error_remediation)으로
예외, 무시, 재질문, 결정적 수정, 필드 제거, 응답 포기 등을 선택한다. `REASK`는 실패 이유를
붙여 LLM을 다시 호출하며 `num_reasks` 한도만큼 생성·검증을 반복한다. `FIX_REASK`는 먼저
결정적으로 고치고 재검증한 뒤 실패할 때만 재호출한다.

### 지연과 비용

**공개된 재현 가능한 p50/p95는 없다.**

**[제작사 주장]** [performance 문서](https://guardrailsai.com/guardrails/docs/concepts/performance)는
Guard orchestration이 보통 10ms 미만, validator가 “올바르게 구성하면” 약 100ms를 더한다고
말하지만 하드웨어·validator·표본·분포가 없다. 같은 문서가 ML validator는 GPU에서 ms,
일반 CPU에서 수십 초까지 걸릴 수 있다고 인정하므로 100ms를 제품 보장으로 사용할 수 없다.

**[공식 동작]** 지연 완화는 `AsyncGuard`, 독립 validator의 동시 실행, 전용 inference server,
remote validation, 작은 목적별 re-validator, 문장 단위 스트리밍이다. 규칙을 싸고 빠른 순서로
배치하고 실패 시 이후 작업을 줄이는 구성도 가능하지만 validator가 값을 변환하면 순서 의존성이
생긴다. 범용 결과 cache나 batch가 모든 validator에 자동 적용된다는 공식 보장은 찾지 못했다.

LLM validator는 검증 시도마다 보통 한 번의 judge 호출을 더한다. 원래 생성 1회에 `REASK`
성공 전까지 재생성 호출이 최대 `num_reasks`만큼 추가되고 각 결과를 다시 validator가 검사한다.
validator 자체도 LLM이면 재검증 judge 비용까지 반복된다. 정확한 비용식은 `생성 호출 + 각
LLM validator 호출 + reask 횟수 × (재생성 + 재검증)`이며, 여러 LLM validator는 병렬이어도
토큰 비용이 합산된다.

### 스트리밍과 마스킹

**[공식 동작]** [streaming 문서](https://guardrailsai.com/guardrails/docs/concepts/streaming)는
기본적으로 문장 하나가 쌓일 때 validator를 실행한다. custom validator는 paragraph 등 다른
chunk strategy를 정할 수 있고, `error_spans_in_output`으로 현재까지 실패한 범위를 조회한다.
문서에는 gardevoir식 고정 overlap/holdback 값이 없고, 어떤 API 산출물이 검사 전에 사용자에게
이미 전달됐는지에 대한 강한 비누출 보장도 없다. **선노출 순서는 확인 필요**다.

Streaming에서 공식 지원되는 실패 행동은 `NOOP`와 `EXCEPTION`뿐이다. `REASK`, `FIX`,
`FILTER`, `REFRAIN`, `FIX_REASK`는 지원하지 않는다. 따라서 문장 단위 span을 내더라도 일반적인
스트림 중간 치환을 당연하게 기대하면 안 된다.

DetectPII 같은 validator는 정확한 `ErrorSpan(start, end)`을 반환하고 `<PERSON>`,
`<EMAIL_ADDRESS>`처럼 typed replacement를 적용할 수 있다. 그러나 이는 Guardrails AI 전체의
단일 가명화 계약이 아니라 validator별 동작이다. span을 못 찾았을 때의 fail-open/fail-closed도
validator와 `on_fail` 설정에 달린다.

### 도구·한국어·라이선스

함수 인자나 도구 결과 값을 custom validator로 검사할 수는 있지만, core 문서에는 principal,
tool permission, 승인, taint history를 묶은 action-control 모델이 없다. gardevoir §8의 직접
대체재가 아니다.

한국어 문자열을 통과시키는 프레임워크 제약은 없지만 validator별 모델·패턴에 종속된다. 공식
전체 한국어 평가를 찾지 못했다. “다국어 입력 가능”과 “한국어에서 검증된 안전성”은 다르다.

- core Python 코드: [Apache-2.0](https://github.com/guardrails-ai/guardrails/blob/main/LICENSE).
- 별도 self-hosted `guardrails-api`: [ELSSTIC에서 채택한 source-available 조건](https://github.com/guardrails-ai/guardrails-api/blob/main/LICENSE)이며
  상당 기능을 제3자에게 hosted/managed service로 제공하는 것을 제한한다.
- Hub validator, 포함 모델, 원격 inference API는 각각 별도 라이선스·비용이다.

## 3. OpenAI Guardrails Python

이 절은 package의 [공식 문서](https://openai.github.io/openai-guardrails-python/)와
[공식 저장소](https://github.com/openai/openai-guardrails-python)를 기준으로 했다. 현재
preview이므로 기본 동작과 API가 바뀔 수 있다.

### 동작과 판정

**[공식 동작]** OpenAI client의 drop-in wrapper로 다음 세 stage를 제공한다.

- Preflight: 주 LLM 호출 전. PII mask, URL 등.
- Input: 주 LLM 호출과 병렬. jailbreak 등.
- Output: 생성 결과 위. hallucination, compliance 등.

[Quickstart](https://openai.github.io/openai-guardrails-python/quickstart/)는 OpenAI-compatible
`base_url`도 지원한다고 명시한다. 따라서 guardrail judge 자체나 대상 모델을 호환 endpoint로
바꿀 수 있지만, package를 gardevoir 서버 안에 넣는 것과 gardevoir를 대상으로 평가하는 것은
다른 배치다.

판정은 혼합형이다. URL은 결정적 allow/block list, PII는 Presidio 기반 span, Moderation은
확률적 API score, Jailbreak·Prompt Injection·Custom Prompt·Hallucination은 LLM/API 기반
확률 판정이다. 실행 오류는 기본적으로 `tripwire_triggered=false`로 계속하는 fail-safe이며,
`raise_guardrail_errors=true`로 fail-secure를 선택해야 한다. 이 기본값은 보안 프록시에는
중요한 차이다.

### 지연, 호출 수, 비용

여러 guardrail은 stage 안에서 동시 실행되어 wall time은 대체로 가장 느린 검사에 지배되지만,
각 LLM/API 호출의 토큰·요금은 모두 더해진다. 규칙/PII를 preflight에 두고 LLM과 input 검사를
겹치며, reasoning 출력을 끄고 짧은 모델을 선택하는 것이 주요 완화책이다. package 전체 cache,
batch, sliding-window early exit는 공식 문서에서 찾지 못했다.

**[제작사 실측]** [Jailbreak check](https://openai.github.io/openai-guardrails-python/ref/checks/jailbreak/)의
TTC는 다음과 같다. 31,106개 구성 풀에서 4,000개를 50/50으로 뽑은 제작사 벤치마크이며,
한국어 데이터라고 명시되지 않았다.

| judge 모델 | p50 | p95 |
| --- | ---: | ---: |
| gpt-4.1-mini | 1,538ms | 2,089ms |
| gpt-4.1 | 2,998ms | 4,204ms |
| gpt-5-mini | 7,055ms | 11,579ms |
| gpt-5 | 7,370ms | 12,218ms |

**[제작사 실측]** 같은 문서는 `include_reasoning=false`가 제작사 평가에서 median 지연을 평균
40%(모델별 18~67%) 줄였다고 한다. 출력 token과 비용도 줄어든다.

**[제작사 실측]**
[Prompt Injection check](https://openai.github.io/openai-guardrails-python/ref/checks/prompt_injection_detection/)는
gpt-4.1-mini 1,481/2,563ms, gpt-4.1 1,742/2,296ms, gpt-5 3,994/6,654ms,
gpt-5-mini 5,895/9,031ms의 p50/p95를 공개한다. 데이터는 AgentDojo와 synthetic 중심이며
한국어 근거가 아니다.

**[제작사 실측]**
[Hallucination check](https://openai.github.io/openai-guardrails-python/ref/checks/hallucination_detection/)는
OpenAI File Search와 LLM을 함께 써 3MB vector store에서 gpt-4.1-mini p50 7,069ms/p95
43,174ms, gpt-4.1 7,126/33,464ms, gpt-5-mini 23,013/59,316ms, gpt-5
34,135/525,854ms를 보고한다. 검색 저장소·문서 길이·서비스 변동이 포함된 특정 workflow 수치로
봐야 한다.

LLM check 하나는 평가 지점마다 judge 호출 하나를 추가한다. tool Prompt Injection은 각 도구
cycle의 호출 전과 결과 후에 각각 한 번이므로 **도구당 2회**다. 여러 check를 켜면 호출 수와
토큰 비용이 선형으로 더해진다. Hallucination은 Responses/File Search workflow 비용, Moderation은
API 호출이지만 현재 OpenAI 문서상 token 비용이 없고, PII/URL은 로컬이다. 가격은 변동하므로
이 문서에 숫자로 고정하지 않았다.

### 스트리밍과 마스킹

**[공식 동작]** [Streaming vs Blocking](https://openai.github.io/openai-guardrails-python/streaming_output/)은
비스트리밍에서 전체 출력을 버퍼링하고 검사를 끝낸 뒤 노출한다. 스트리밍에서는 preflight와
input guardrail을 먼저 끝내지만, 모델 출력은 즉시 사용자에게 보내고 output guardrail을
병렬로 실행한다. 공식 문서가 위반 텍스트가 잠깐 보일 수 있음을 명시한다. 문장/청크/overlap/
holdback 계약은 없다. 따라서 §9의 비누출 요구에는 비스트리밍만 맞고, streaming 모드는 맞지
않는다.

**[공식 동작]** Contains PII는 Presidio와 필수 `en_core_web_sm`을 쓰고 Unicode normalization,
일부 encoded PII 탐지를 제공한다. preflight 입력은 typed placeholder로 mask할 수 있지만
output masking은 지원하지 않고 output에서는 차단해야 한다. 영어 spaCy 모델이 필수라는 점에서
한국어 PII의 실지원 근거가 없다.

### 도구 통제, 한국어, 라이선스

Agents SDK 통합에서 Prompt Injection check는 도구 호출 전 사용자 목표·대화 이력과 예정된
도구 호출이 의미적으로 맞는지, 도구 결과 후 그 결과가 원래 의도와 정렬되는지를 LLM으로 본다.
기본은 위반 content만 거부하고 agent는 계속하며, `block_on_tool_violations=true`로 전체 실행을
멈출 수 있다.

이는 유용한 semantic alignment지만 principal 권한, 결정적 schema, 승인, 결과 provenance를
증명하지 않는다. gardevoir ④/②에 보완적으로 붙일 수는 있어도 대체할 수 없다.

LLM check는 선택 모델의 언어 능력을 물려받지만 package의 공개 benchmark는 한국어 평가가
아니다. PII는 명시적으로 영어 모델을 요구하고 Moderation도 package 문서에 한국어별 성능이
없다. **한국어 실지원은 확인 필요**다.

- 코드: [MIT](https://github.com/openai/openai-guardrails-python/blob/main/LICENSE).
- OpenAI API 모델·File Search·외부 서비스는 서비스 약관과 사용량 요금이 별도다.
- Presidio와 spaCy 모델도 제3자 구성요소 라이선스를 별도로 확인해야 한다.

## 4. Llama Guard 4

### 동작, 지연, 스트리밍

**[공식 동작]** [Llama Guard 4 12B 모델카드](https://huggingface.co/meta-llama/Llama-Guard-4-12B)는
Llama 4 Scout에서 pruning한 12B dense multimodal generative classifier라고 설명한다. 사용자
prompt 또는 모델 response와 이미지들을 받아 `safe`/`unsafe`와 위반 category를 짧게 생성한다.
입력 전·출력 후에 integrator가 호출하는 모델이지 독립 proxy runtime은 아니다.

`do_sample=false`, 짧은 `max_new_tokens`로 형식을 안정화할 수 있어도 신경망 판정 자체는
확률적이다. span, 수정문, 가명화 mapping을 내지 않는다.

**공식 wall-clock p50/p95·throughput은 없다.** 로컬 또는 inference server에서 체크포인트당
한 번 추론한다. 모델카드는 single GPU 실행과 vLLM/SGLang 경로를 안내하므로 serving runtime의
batching·continuous batching을 이용할 수 있지만, 이는 모델카드의 지연 보장이나 공개 실측이
아니다. 출력 토큰을 10개 정도로 제한하고 조기 stop하는 것은 decode 비용만 줄이며 긴 입력의
prefill 비용은 남는다.

네이티브 streaming 검사 단위는 없다. 완성된 prompt/response를 모델 입력으로 조립해야 하므로
통합자가 전체 버퍼링하거나 임의의 청크·문장 샘플링을 구현해야 한다. 부분 청크를 반복 판정하면
추론 횟수와 비용이 청크 수만큼 늘고, 문맥이 잘린다.

### 마스킹·도구·한국어·라이선스

마스킹 span이 없으므로 차단 또는 전체 응답 대체에 적합하다. gardevoir가 모델 verdict에
`MASK`를 허용하지 않는 결정은 Llama Guard 4 같은 classifier와 맞는다.

S14 `Code Interpreter Abuse`는 denial of service, container escape, privilege escalation을
돕는 텍스트를 분류하는 카테고리다. 임의 도구의 name/argument/schema, caller 권한, 사용자 승인,
실행 결과를 보는 action-control은 아니다.

**[제작사 실측]** 모델카드의 사내 output-filter 평가 평균은 English recall 69%, FPR 11%,
F1 61%; multilingual recall 43%, FPR 3%, F1 51%; single-image F1 38%, multi-image F1 52%다.
Multilingual 평균은 French, German, Hindi, Italian, Portuguese, Spanish, Thai의 7개 언어이며
**한국어가 없다.** 따라서 한국어 지원·평가 근거가 없다.

- 모델 코드·가중치·inference-enabling code: OSI permissive가 아닌
  [Llama 4 Community License](https://huggingface.co/meta-llama/Llama-Guard-4-12B). 배포 시
  `Built with Llama`, NOTICE, Acceptable Use Policy 조건이 있고 출시 시점 직전 월 MAU가
  7억 초과인 사업자는 Meta의 별도 라이선스가 필요하다.
- 이를 감싸는 우리 adapter 코드의 라이선스와 Llama 가중치 라이선스는 별개다.

## 5. Granite Guardian

### 동작과 지연

**[공식 동작]** 최신 [Granite Guardian 4.1 8B 모델카드](https://huggingface.co/ibm-granite/granite-guardian-4.1-8b)를
기준으로 했다. 대화·문서·도구 정보를 prompt에 넣고, 사전 정의 criterion 또는 자연어 BYOC
criterion에 대해 `<score>yes|no</score>`를 생성하는 8B judge다. input/output 안전, jailbreak,
RAG context relevance·groundedness·answer relevance, function-call hallucination을 검사한다.

모델카드가 “deterministic binary output”이라고 부르는 것은 출력 schema가 yes/no로 고정된다는
뜻이다. temperature 0에서도 어떤 쪽을 고르는 신경망 판정은 확률적이다.

**공식 wall-clock p50/p95·throughput은 없다.** criterion 하나와 sample 하나당 보통 local
inference 한 번이다. 여러 criterion을 별도 실행하면 호출 수가 늘어난다. 자연어 criterion을
합쳐 한 번에 검사할 수는 있지만 criterion별 calibration과 원인 구분을 잃을 수 있다는 것은
**[추정]**이다. `no-think`는 reasoning을 생략해 더 낮은 지연을 목표로 하고, 모델카드는 stricter
latency가 필요하면 범위가 더 좁은 HAP-38M 같은 작은 모델을 쓰라고 한다. cache·batch·실측
수치는 공개하지 않았다.

네이티브 streaming rail은 없다. 대화, retrieval document, tool schema와 완성된 판정 대상을
함께 넣으므로 통합자가 전체 항목을 버퍼링하는 것이 기본이다. 청크 샘플링은 별도 구현이며
공식 정확도 근거가 없다.

### tool-call hallucination의 실체

**[공식 동작]** 이 판정은 대화 속 user query, assistant가 직렬화한 function call, 사용 가능한
tool definitions를 본다. 정의되지 않은 함수, 잘못된 호출 format, 잘못된 argument name/value/type,
query나 tool definition과 모순되는 호출을 잡으려 한다.

보지 않는 것은 실제 실행, caller의 권한, side effect, 승인 상태, 결과 provenance다. 따라서
`amount=1000000`이 JSON Schema상 숫자이며 사용자 요청과 그럴듯하게 맞으면 사업 정책 한도를
증명하지 못한다. Granite는 **semantic/schema hallucination judge**, gardevoir는 **정책 집행자**다.

**[제작사 실측]** FC Reward Bench balanced accuracy는 3.3 8B no-think 0.74/think 0.71,
4.1 8B no-think 0.79/think 0.78이다. 이는 탐지 품질 지표이지 지연 측정이 아니다.

### 마스킹·Retrieval·한국어·라이선스

yes/no와 선택적 reasoning만 내므로 span 기반 마스킹은 하지 못한다. Retrieval criterion은
문서와 답변의 관련성·groundedness를 사후 판정할 수 있지만, 문서 ACL이나 source trust를
결정적으로 강제하지 않는다.

모델카드는 **영어 데이터로만 학습·시험**했다고 명시한다. 한국어 실지원 근거가 없다.

- 모델 가중치와 공식 저장소: [Apache-2.0](https://huggingface.co/ibm-granite/granite-guardian-4.1-8b).
- inference runtime·tokenizer 등 제3자 의존성은 각 라이선스를 따로 확인한다.

## 6. Presidio

### span을 얻는 방법과 실패 의미

**[공식 동작]** Presidio Analyzer는 정규식, deny-list, checksum, context, custom logic,
spaCy/Stanza/Transformers/GLiNER 같은 NER를 조합한다. 규칙·checksum은 결정적이고 NER score는
확률적이다. 결과는 `RecognizerResult(entity_type, start, end, score)`로 정확한 문자 span을
준다. Anonymizer는 텍스트를 다시 찾지 않고 이 span 목록과 operator를 입력으로 받는다.
[공식 Anonymizer 문서](https://presidio.dataprivacystack.org/anonymizer/)가 이 계약을 예제로
명시한다.

**[추정]** detector가 민감정보를 못 찾아 `RecognizerResult`를 만들지 않으면 Anonymizer가
적용할 span도 없으므로 원문이 그대로 남는다. Anonymizer는 탐지 실패를 fail-closed로 바꾸지
않는다. 따라서 score threshold, recognizer coverage, unsupported language가 마스킹의 실제
보안 경계다. 호출자는 “0 findings”를 정상 통과로 볼지 별도 보수 정책을 둘지 정해야 한다.

겹치는 span은 완전 중첩이면 높은 score, 포함 관계면 더 긴 span, 부분 교차면 두 anonymized
결과를 이어 붙인다. 이는 의도치 않은 중복 placeholder가 될 수 있어 회귀 사례가 필요하다.

### Replace·Redact·Hash·Mask·Encrypt

| operator | 실제 동작 | 가역성 | 상태·주의점 |
| --- | --- | --- | --- |
| Replace | span을 `new_value`로 치환. 값이 없으면 `<ENTITY_TYPE>` | Presidio 자체로 비가역. 외부 mapping을 저장하면 사실상 가명화 가능 | typed placeholder로 의미·타입을 보존할 수 있음 |
| Redact | span을 빈 문자열로 삭제 | 비가역 | 주변 문장 결합으로 새 패턴이 생길 수 있음 |
| Hash | 기본 SHA-256, 선택 SHA-512 salted hash로 치환 | 일방향이며 decrypt 불가 | 2.2.361부터 기본은 entity별 random salt라 동일 값도 달라짐. 일관된 사용자 salt를 주면 referential integrity를 얻지만 salt를 외부에서 안전하게 관리해야 함 |
| Mask | 시작 또는 끝에서 `chars_to_mask`개를 `masking_char`로 바꿈 | 원문 없이는 비가역 | 일부 문자를 남기는 부분 마스킹 가능. 길이와 일부 값이 노출됨 |
| Encrypt | 사용자 key로 암호문으로 치환 | 같은 key의 decrypt operator로 가역 | key 저장·회전·권한·감사·암호문 크기 관리가 필요 |

Presidio에는 mapping/Faker를 이용한 pseudonymization sample도 있지만, core가 상태ful session을
보관하지 않는다. stable placeholder나 salt·key·mapping의 수명주기는 사용자가 소유한다.

gardevoir의 상수 placeholder 한 종류는 구현은 단순하고 재식별 상태를 만들지 않지만 타입,
동일인 참조, 부분 노출 같은 정책 선택을 모두 잃는다. 반면 모델 classifier에 span이 없는 문제는
Presidio operator 종류를 늘린다고 해결되지 않는다. span-producing rule/recognizer에서만 허용해야
한다는 현재 경계는 유지할 근거가 있다.

### 지연, 스트리밍, 한국어, 라이선스

Presidio maintainer는 구성 가능한 프레임워크라 공식 범용 benchmark를 제공하지 않는다고
[성능 discussion](https://github.com/microsoft/presidio/discussions/1226)에서 설명했다.
**범용 p50/p95는 없다.** 로컬 정규식·checksum은 네트워크 호출이 없고, batch analyzer와
multi-process, GPU NER를 쓸 수 있다. [CHANGELOG](https://github.com/data-privacy-stack/presidio/blob/main/CHANGELOG.md)의
GLiNER/Transformers/Stanza GPU 4~10배는 제작사 주장/특정 최적화이며 절대 지연값이 아니다.
규칙을 먼저 쓰고 필요한 entity에만 무거운 NER를 붙이는 것이 가장 예측 가능한 경로다.

Presidio text API에는 SSE holdback/sliding window가 없다. 전체 문자열 또는 batch를 검사한다.
스트림에 쓰려면 호출자가 문장/청크를 모으고 overlap과 global offset mapping을 구현해야 한다.
단순 청크 경계는 주민번호·이메일·이름을 둘로 잘라 누락할 수 있다.

[지원 entity 문서](https://github.com/data-privacy-stack/presidio/blob/main/docs/supported_entities.md)에는
`KR_DRIVER_LICENSE`, `KR_FRN`, `KR_PASSPORT`, `KR_BRN`, `KR_RRN`이 있다. 그러나 현재
[기본 recognizer 설정](https://raw.githubusercontent.com/data-privacy-stack/presidio/main/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml)에서
한국 recognizer는 disabled이고 기본 supported language는 영어다. 한국 이름·주소도 별도 한국어
NLP/custom recognizer가 필요하다. 한국어 precision/recall 공식 수치는 찾지 못했다.

- 코드: 프로젝트가 data-privacy-stack으로 이관됐으며 [MIT](https://github.com/data-privacy-stack/presidio/blob/main/LICENSE).
- spaCy/GLiNER/Transformers 등 선택 모델 가중치는 별도 라이선스다.

## 7. Promptfoo

### gardevoir를 직접 겨눌 수 있는가

**가능하다.** [OpenAI provider 문서](https://www.promptfoo.dev/docs/providers/openai/)는
`openai:chat:<model>`이 `/v1/chat/completions`를 호출하고 `apiBaseUrl`에 OpenAI-compatible
gateway를 넣을 수 있다고 명시한다. gardevoir의 `/v1` base URL, gardevoir API key header,
실제 또는 안전한 stub upstream model을 지정하면 비스트리밍 요청을 그대로 평가할 수 있다.

다만 target call이 통과한 뒤 실제 upstream 비용·side effect가 발생할 수 있다. CI에서는
별도 test credential, 허용 모델, mock/stub provider, 외부 도구를 실행하지 않는 fixture가
필수다. Promptfoo 자체의 기본 target 호출은 §9 SSE event timing과 “검사 전 1바이트도 새지
않음”을 증명하지 않는다. 그 검사는 custom HTTP/provider 또는 별도 SSE harness가 필요하다.

### 동작, 비용, 성능

Promptfoo는 runtime guardrail이 아니라 offline/CI evaluation·red-team runner다. plugin이 공격
prompt를 만들고 strategy가 변형·반복하며 target을 호출한 뒤 assertion/detector/LLM grader로
통과 여부를 정한다. 정적 assertion은 결정적이고 LLM rubric·moderation·adaptive attack은
확률적이다.

**제품 전체 p50/p95는 없다.** 총 시간과 비용은 대략 `생성된 test 수 × strategy 배수 × target
호출 + grader 호출 + attacker 호출`이다. [red-team 설정](https://www.promptfoo.dev/docs/red-team/configuration/)의
기본 `numTests`는 plugin당 5이고, target과 공격 생성·grading provider는 분리할 수 있다.
일반 test는 target을 최소 한 번 호출하고 model-graded assertion은 grader 호출을 더한다.
iterative strategy는 성공 또는 최대 반복까지 attacker feedback과 target 호출을 반복하므로
폐쇄형 고정 호출 수가 없다. 정확한 상한은 선택 plugin/strategy/grader마다 **확인 필요**다.

지연 완화 수단은 concurrency·delay·retry/backoff, 관련 plugin만 선별, test 수 축소, 정적 corpus
재사용이다. 성공 API response는 기본 disk cache를 쓸 수 있지만 회귀검증에서 오래된 안전 결과를
재사용하지 않도록 CI는 cache key와 TTL 또는 `--no-cache` 정책을 명시해야 한다. adaptive/LLM
attack은 비용과 비결정성이 크므로 PR gate보다 야간 실행이 알맞다.

### 한국어·CI·라이선스

[설정 문서](https://www.promptfoo.dev/docs/red-team/configuration/#language)는 full language name
또는 ISO 639-1 code와 여러 언어를 허용하므로 `Korean`/`ko`를 지정할 수 있다. 이는 생성 옵션일
뿐 한국어 attack/grader 품질 평가가 아니다. 공격·grader 모델이 한국어를 잘못 번역하거나
완곡 표현을 놓칠 수 있으므로 사람이 검수한 고정 한국어 corpus와 결정적 HTTP status/verdict
assertion을 기본 gate로 삼아야 한다.

[CI/CD 문서](https://www.promptfoo.dev/docs/integrations/ci-cd/)는 GitHub Actions, GitLab CI,
Jenkins, JSON/HTML/JUnit 출력과 실패 threshold를 지원한다. 따라서 실제 도입 가능성은 높다.

- core 코드: [MIT](https://github.com/promptfoo/promptfoo/blob/main/LICENSE).
- 모델 가중치를 묶어 배포하지 않는다. 선택한 attacker/target/grader API와 로컬 모델의 라이선스·
  토큰 비용은 별도다.

## 8. garak

### gardevoir를 직접 겨눌 수 있는가

**가능하다.** 공식 저장소의
[`openai.OpenAICompatible` generator](https://github.com/NVIDIA/garak/blob/main/garak/generators/openai.py)는
기본 `/v1/` URI에서 OpenAI client의 Chat Completions를 호출하고 model name·API key를 설정한다.
gardevoir base URL과 credential을 주면 완성 응답 기준 probe를 실행할 수 있다.

Promptfoo와 마찬가지로 기본 generator는 SSE 청크 누출이나 128자 holdback을 관찰하는 테스트가
아니다. tool action side effect를 가진 실제 upstream을 연결하지 말고 격리된 test provider를
써야 한다.

### 동작, 비용, 성능

garak은 probe가 공격 입력을 만들고 generator가 target을 호출하며 detector가 완성 응답을
채점하고 evaluator가 집계하는 offline scanner다. probe는 정적·조합·동적·반응형이 있고,
detector는 keyword/regex 같은 결정적 방식부터 local/API classifier까지 혼합한다. JSONL report와
hit log가 회귀 자료가 된다. 공식 [FAQ](https://github.com/NVIDIA/garak/blob/main/FAQ.md)는 probe별
score가 과학적으로 정규화돼 서로 직접 비교되는 지표가 아니라고 경고한다.

**제품 전체 p50/p95는 없다.** [가속 문서](https://reference.garak.ai/en/latest/faster.html)는
default run이 80,000회 이상의 inference request가 될 수 있다고 한다. 기본 generation 5를
줄이면 호출량이 직접 줄지만, 1은 일시적 확률 행동을 놓쳐 최소 2를 권장한다. prompt cap을
낮추면 시간과 coverage를 맞바꾸며, remote endpoint에서는 `parallel_attempts`로 동시화할 수
있다. probe 자체는 순차이므로 여러 job으로 probe를 나누고 report를 aggregate해야 더 크게
병렬화된다. detector나 adaptive probe가 모델/API를 쓰면 별도 호출·비용이 추가된다.

### 한국어·CI·라이선스

[Translation Support](https://reference.garak.ai/en/latest/translation.html)는 probe·detector의
keyword/trigger를 번역할 수 있지만 현재 문장 구조가 BCP47 `en`에 강하게 결합돼 있고,
Hugging Face detector는 주로 영어 모델이며 일부는 역번역이나 대상 언어 NLI 모델이 필요하다고
명시한다. 번역은 local 모델 다운로드 또는 cloud API와 상당한 실행 시간을 요구할 수 있다.
그러므로 한국어는 기술적으로 경로가 있지만 **native 한국어 평가·품질 보장은 없다.** 이번
조사에서는 어떤 모델도 다운로드하지 않았다.

CLI를 CI job에서 실행하고 JSONL/HTML report를 artifact로 보관할 수 있다. 그러나 공개 OSS
문서에서 안정적인 `pass-rate < X이면 non-zero exit` 같은 1급 regression gate 계약은 찾지
못했다. JSONL을 후처리해 자체 threshold를 적용하는 방안은 가능하지만 report schema와 parser의
pre-1.0 호환성은 고정 버전에서 검증해야 한다. **native CI gate 동작은 확인 필요**다.

- 코드: [Apache-2.0](https://github.com/NVIDIA/garak/blob/main/LICENSE).
- 선택한 local detector/translation/attacker 모델 가중치와 cloud API는 각각 별도 조건이다.

## 지연·호출 비용 요약

| 대상 | 공개 wall-clock 실측 | judge 호출 구조 | 공식 지연 대응 |
| --- | --- | --- | --- |
| NeMo | 범용 p50/p95 없음. 2023 dialog 구조는 약 3배 비용·지연 | rail/flow별 가변, 고전 dialog 최대 여러 순차 호출 | exact cache, 병렬 rail, speculative generation, local/규칙 선택, streaming chunk |
| Guardrails AI | 재현 가능한 p50/p95 없음. sub-10ms/100ms는 제작사 주장 | LLM validator마다 시도당 호출, reask 때 재생성·재검증 반복 | AsyncGuard, validator 동시성, remote inference, 작은 re-validator, 문장 단위 |
| OpenAI Guardrails | 특정 check별 p50/p95 공개 | LLM check당 지점별 1회, tool injection은 cycle당 2회, 비용 합산 | preflight, input과 generation 병렬, reasoning 생략, 모델 선택 |
| Llama Guard 4 | 없음 | 체크포인트당 local inference 1회 | 짧은 decode, local serving, serving runtime batching 가능 |
| Granite Guardian | 없음 | criterion/sample당 보통 1회 | no-think, 작은 범위별 모델, local serving |
| Presidio | 범용 없음 | 기본은 LLM 0회 | local 규칙, batch/multiprocess, GPU NER, 규칙 우선 |
| Promptfoo | 없음; runtime 경로 아님 | test당 target ≥1, 선택 grader/attacker/iteration만큼 추가 | concurrency, cache, test/plugin 선별, 정적 corpus |
| garak | 없음; default run 8만+ inference 가능 | prompt × generations × probe, 선택 detector/attacker 추가 | parallel attempts, probe 분할, generation/prompt cap 축소 |

OpenAI 제작사 수치와 gardevoir의 3.36초는 판정 작업, 입력, 서비스/하드웨어가 다르므로 빠르기
순위로 비교할 수 없다. gardevoir가 필요한 다음 측정은 “규칙만”, “분류만”, “span localizer”,
“stream window 반복 판정”을 분리한 end-to-end p50/p95와 upstream generation을 뺀 자체 추가
지연이다.

## 스트리밍 대조

| 대상 | 기본 검사 단위 | 검사 전 노출 | 경계 문맥 |
| --- | --- | --- | --- |
| gardevoir | 128자 holdback, 512자 overlap | 설계상 없음 | 문자 sliding window |
| NeMo | 기본 200 token chunk | `stream_first=true`면 있음; false면 없음 | 기본 50 token overlap |
| Guardrails AI | 기본 문장, custom chunk 가능 | 문서만으로 강한 보장 확인 필요 | 고정 overlap 계약 없음 |
| OpenAI Guardrails | streaming output과 guardrail 병렬 | 공식적으로 잠깐 노출 가능 | window/holdback 없음 |
| Llama Guard 4 | 모델 자체 단위 없음 | integrator 책임 | 완성 prompt/response 권장 |
| Granite Guardian | 모델 자체 단위 없음 | integrator 책임 | 대화·문서·도구 전체 문맥 |
| Presidio | 전체 text/batch | integrator 책임 | 자체 streaming/overlap 없음 |
| Promptfoo·garak | 완성 target response | runtime 스트림 검증 아님 | 별도 SSE harness 필요 |

NeMo의 `stream_first=false`가 가장 가까운 공개 비교 대상이다. gardevoir §9의 장점은 토큰 200개가
찰 때까지 기다리지 않고 고정 128자만 보류한다는 점이고, 약점은 문자 단위가 tokenizer/문장
경계와 무관하며 512자보다 긴 우회 문맥은 놓칠 수 있다는 점이다. 이 수치는 공개 도구가 정답을
증명해 주지 않으므로 한국어·이모지·결합문자·SSE split을 포함한 회귀 실측으로 방어해야 한다.

## Retrieval rail과 Dialog rail은 무엇을 더 막는가

### Retrieval rail

NeMo가 말하는 Retrieval rail은 검색 직후, LLM prompt 조립 전에 문서·chunk를 검사·변환하는
경계다. 여기서 막을 수 있는 것은 다음과 같다.

- 문서의 tenant/ACL, 출처 신뢰도, freshness, 문서 유형 같은 metadata 기반 제외.
- 검색 문서 안의 prompt injection, PII, 악성 URL/명령.
- query와 chunk의 관련성, context bloat, 중복 또는 너무 많은 문서.
- 모델이 보지 않아야 할 원문을 먼저 mask하거나, 낮은 신뢰 문서를 제거.

gardevoir ② `tool_result`와 겹치는 경우는 retrieval이 OpenAI tool call/result로 드러나고 결과
본문이 프록시를 통과할 때다. 그래도 ②는 검색 후보·랭킹·source metadata를 알지 못하고, 결과가
하나의 큰 문자열이면 문서별 정책도 적용하기 어렵다. 애플리케이션 내부 RAG가 최종 user message나
system prompt에 context를 합쳐 보내면 retrieval 경계 자체가 보이지 않는다. ④는 어떤 retrieval
tool을 호출할지 통제할 뿐 어떤 chunk가 반환·선택되는지는 통제하지 않는다.

**[판단]** core proxy에 검색 엔진을 직접 넣을 필요는 없다. 대신 선택적인 표준 extension으로
`retrieval_context[] = {content, source, tenant, trust, acl, rank}`를 받아 ②와 구분해 검사하거나,
검색기 adapter가 gardevoir inspection API를 호출하도록 해야 한다. 애플리케이션 협조가 없는
완전 투명 프록시만으로는 이 공백을 닫을 수 없다. ACL은 확률 모델보다 결정적 규칙이 먼저여야
한다.

### Dialog rail

Dialog rail은 “이 발화가 안전한가”보다 “현재 상태에서 다음 전이가 허용되는가”를 본다.

- 본인 확인 전 계정 정보 조회 금지.
- 금액·위험 등급에 따라 안내 → 요약 → 명시적 확인 → 실행 순서 강제.
- 한 번 거절된 요청을 여러 턴으로 분해해 재시도하는 escalation 제한.
- topic/role별 허용 flow와 반드시 실행돼야 하는 handoff.

gardevoir의 대화 taint는 이전 위험 신호를 다음 ④ action 판단에 반영하므로 multi-turn 공격 일부와
겹친다. 그러나 “확인 메시지가 있었는가”, “두 번째 승인자가 승인했는가”, “상태 A에서만 tool B가
가능한가”를 일반 상태기계로 증명하지 않는다. ②는 결과 내용을 검사할 뿐 flow 순서를 강제하지
않는다.

**[판단]** 범용 proxy가 모든 업무 dialog를 추측해 강제하면 application 의미를 침범한다. 낮은
위험 chat에는 불필요하고, 송금·삭제·권한 변경 같은 고위험 action에는 필요하다. 우선 §8의 승인
흐름을 명시적 action state machine으로 만들고, 이후 애플리케이션이 flow ID/state/evidence를
서명해 전달하는 선택적 계약이 적합하다. NeMo식 자연어 flow를 그대로 core domain에 넣는 것은
도입비용과 LLM 호출 지연이 크다.

## gardevoir 대조표

| 대상 | 계층 커버리지 | 판정 방식 | 지연 대응 | 스트리밍 | 마스킹 | 도구·action | 한국어 근거 | 코드 / 가중치·서비스 라이선스 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gardevoir | ① input, ② tool_result, ③ output, ④ tool_call | 규칙 우선 + model tier | 규칙 선행, async audit batch; 모델 경로 수치 재정의 필요 | 128자 holdback + 512자 overlap, tool JSON 전체 | span rule만 상수 placeholder; 가역 없음 | policy allowlist/args + taint, 승인 미구현 | 자체 짧은 한국어 실측은 있으나 넓은 eval 부족 | 저장소에 LICENSE 파일 없음: 확인 필요 / 선택 모델별 |
| NeMo | input/retrieval/dialog/execution/output | Colang·규칙·분류기·LLM/API 혼합 | cache, 병렬, speculative, local | 200 token/50 overlap, 기본 선노출 | detector별 span mask | IORails allowlist+JSON Schema+result 구조; 내용·권한은 별도 | 전체 공식 한국어 eval 없음 | Apache-2.0 / 모델·API별 |
| Guardrails AI | input/output/value validation | validator별 결정적/확률적 | async, remote, 동시성, revalidator | 기본 문장; 비누출 보장 확인 필요 | validator별 span/fix/typed replace | generic validator, 권한 모델 없음 | validator별, 전체 eval 없음 | core Apache-2.0, server 제한 라이선스 / validator·모델별 |
| OpenAI Guardrails Python | preflight/input/output + Agents tool 전후 | URL/PII 규칙 + Moderation/LLM | 병렬 stage, reasoning 생략, 모델 선택 | streaming은 선노출, non-stream은 전체 buffer | input Presidio typed mask; output mask 불가 | 사용자 의도 semantic check, 권한/schema 아님 | PII 영어 필수, package 한국어 eval 없음 | MIT / API 약관·비용별 |
| Llama Guard 4 | input/output classifier | 12B 확률 모델 | local serving, 짧은 decode; 공개 지연 없음 | integrator 책임, 보통 전체 | span 없음 | S14 코드 인터프리터 악용 콘텐츠만 | 평가 7개 비영어에 한국어 없음 | Llama 4 Community License |
| Granite Guardian | input/output, RAG, tool-call judge | 8B 확률 yes/no judge | no-think, 작은 모델; 공개 지연 없음 | integrator 책임, 전체 문맥 | span 없음 | 없는 함수·형식·인자·query 불일치; 권한/실행 아님 | 영어만 학습·시험 | Apache-2.0 weights/repo |
| Presidio | text/image/structured PII 분석·익명화 | 규칙/checksum + NER 혼합 | local, batch/process, GPU NER | 자체 streaming 없음 | Replace/Redact/Hash/Mask/Encrypt | 없음 | KR ID 패턴은 있으나 기본 disabled, 품질 수치 없음 | MIT / NLP 모델별 |
| Promptfoo | offline eval/red team | assertion·detector·LLM grader 혼합 | concurrency/cache/test 선별 | 완성 응답, SSE 별도 | runtime 마스킹 아님 | 공격·정책 회귀, 직접 집행 아님 | `ko` 생성 가능, 공식 품질 eval 없음 | MIT / provider·모델별 |
| garak | offline vulnerability scan | probe + detector 혼합 | 병렬 attempt, job 분할, cap 축소 | 완성 응답, SSE 별도 | runtime 마스킹 아님 | attack probe, 직접 집행 아님 | 번역 경로 있으나 영어 결합·품질 미검증 | Apache-2.0 / detector·번역 모델별 |

## 세 질문에 대한 답

### 1. 우리가 빠뜨린 것은 무엇인가

1. **Retrieval 경계**: ②가 외부로 드러난 tool result를 검사하는 것은 맞지만 내부 RAG의 문서별
   ACL·source trust·rank·chunk injection을 보지 못한다. 완전히 겹치지 않는다.
2. **Dialog/업무 흐름 경계**: taint와 ④는 action 단위 방어이며, 선행 조건과 승인 단계를 가진
   여러 턴 state machine은 아니다. 고위험 workflow에 공백이 있다.
3. **레드팀 회귀**: 현재 정책 compiler와 smoke verification만으로는 jailbreak 변형, 다국어
   우회, prompt injection, over-refusal의 시간에 따른 퇴행을 보지 못한다. Promptfoo/garak을
   넣되 고정 한국어 corpus가 기준이고 동적 공격은 보조여야 한다.
4. **도구 JSON Schema와 결과 provenance**: NeMo 비교에서 드러난 저비용 공백이다. 이름·regex
   인자 정책과 별도로 OpenAI tool definition의 schema를 완성 JSON에 결정적으로 적용하고,
   tool_result가 어떤 승인된 call의 결과인지 연결해야 한다. 현재 구현 여부는 확인 필요다.
5. **실패 정책 명시**: 외부 모델/API timeout, recognizer 0건, unsupported language를 fail-open할지
   fail-closed할지 rail별로 명시해야 한다. OpenAI Guardrails의 기본 fail-safe는 그대로 답습하면
   안 된다.

### 2. 우리가 다르게 한 것 중 근거가 약한 것은 무엇인가

#### 상수 placeholder 한 종류

근거가 가장 약하다. 상수 하나는 상태·키 관리가 없고 출력에서 entity type을 숨길 수 있다는
장점은 있지만 다음을 포기한다.

- `<PERSON>`/`<KR_RRN>` 같은 타입 보존.
- 같은 값이 다시 등장했음을 알아보는 referential integrity.
- 카드 끝 4자리처럼 정책적인 부분 마스킹.
- 승인된 내부 처리 후 복원하는 가역 가명화.

**[판단]** 기본을 non-reversible typed replacement로 넓히는 것은 낮은 비용이다. stable hash는
salt 관리 때문에 중간 비용, Encrypt는 key vault·rotation·access log·retention 때문에 높은
비용이다. 모든 모드를 한꺼번에 넣기보다 정책 action을 `REPLACE_TYPED`, `REDACT`,
`MASK_PARTIAL`로 먼저 분리하고, hash/encrypt는 별도 위협모델 뒤에 도입해야 한다. 모델 판정에
span이 없으면 여전히 모든 span action을 저작 시점에 거부해야 한다.

#### “모델 티어 p50 3.36초”

표현의 근거가 약하다. 값 자체는 실측이지만 범위가 잘못 일반화됐다. 정확한 표현은 “Qwen 기반
guided-JSON span localizer가 동일한 짧은 한국어 문장 n=7에서 p50 3.3618초”다. classifier,
원격 LLM judge, 긴 입력, GPU concurrency, streaming window 반복 호출을 대표하지 않는다.

**[판단]** 제품 SLO는 `deterministic`, `classifier`, `localizer`, `remote judge` 경로를 나눠
추가 지연을 측정하고, p50/p95와 sample 수·input length·cold/warm·concurrency를 같이 기록해야
한다. OpenAI 공개표가 보여 주듯 judge 모델 선택만으로도 1.5초에서 7초 이상까지 달라진다.

#### 승인 흐름 미구현

이는 단순한 기능 backlog보다 action-control의 실제 공백이다. block/allow 두 값만 있으면
불확실하지만 큰 피해가 가능한 작업을 과도하게 차단하거나 위험하게 허용하게 된다. §8이 사람
승인이 더 맞는 경우를 이미 인정하므로 미구현 상태를 차별점처럼 말할 근거가 없다.

**[판단]** 승인에는 단순 UI보다 승인 요청 snapshot, actor·tenant binding, policy/version binding,
만료, one-time nonce, replay 방지, idempotency, 원래 tool args hash, 승인자 분리, 취소, 감사가
필요하다. 도입비용은 높지만 송금·삭제·권한 변경을 목표로 한다면 Retrieval/Dialog보다 먼저다.

### 3. 바로 가져올 수 있는 것과 도입비용

| 제안 | 출처/근거 | 예상 비용 | 권장 순서 |
| --- | --- | --- | --- |
| 도구 호출 완성 JSON에 JSON Schema 검증 | NeMo IORails | 낮음~중간. 기존 OpenAI tool schema 보존·검증 오류 contract 필요 | 즉시 |
| typed Replace/Redact/부분 Mask action | Presidio operator 구분 | 낮음~중간. compiler·wire action·audit 변경 필요, 키 상태 없음 | 즉시 |
| Promptfoo 고정 한국어 corpus PR gate | OpenAI-compatible provider, CI/JUnit | 낮음. Node 의존성 도입 결정과 안전한 test upstream 필요 | 즉시 설계, 별도 구현 작업 |
| SSE leak regression harness | NeMo/OpenAI streaming 비교 | 낮음~중간. byte/event timing 검사와 boundary corpus 필요 | 즉시 |
| garak 선별 probe 야간 scan | OpenAICompatible generator | 중간. Python 의존성·버전 pin·JSONL gate·영어 편향 관리 | 다음 |
| stable salted hash 가명화 | Presidio Hash | 중간. salt secret·rotation·referential scope 설계 | 위협모델 후 |
| retrieval context extension | NeMo Retrieval rail | 중간~높음. 앱/검색기 협조와 metadata contract 필요 | RAG 고객 요구 시 |
| Encrypt/decrypt 가명화 | Presidio Encrypt | 높음. key vault·rotation·권한·감사·보존 | 규제 use case 시 |
| 승인 workflow | §8 공백, Dialog/action 비교 | 높음. durable state와 보안 token, UI/API, 감사 | 고위험 action 전 필수 |
| 범용 Dialog DSL | NeMo Dialog rail | 높음. 앱 의미 결합, 상태·버전·지연 | 승인 이후 제한적으로 |

“바로 가져온다”는 이 브랜치에서 설치·구현한다는 뜻이 아니다. 이번 작업은 조사와 문서만 했고,
실제 의존성 추가·모델 다운로드·코드 변경은 하지 않았다.

## Promptfoo·garak 도입안

### PR마다 실행할 결정적 층

- 사람이 검수한 한국어·영어 JSON/CSV corpus: 명시적 allow/block/mask, ①~④ checkpoint,
  URL/PII/도구 이름·인자, 대화 taint, SSE 경계 분할.
- Promptfoo target을 gardevoir `/v1/chat/completions`로 지정하고 `stream=false`, temperature 0,
  고정 mock upstream을 사용한다.
- HTTP status, wire `action`, policy ID/version, placeholder, tool call 차단을 결정적 assertion으로
  검사한다. LLM-as-judge는 PR 필수 gate에서 제외한다.
- 별도 작은 SSE client가 1글자·멀티바이트 UTF-8·이모지·결합문자·128/512 경계로 event를 쪼개
  위반 substring이 verdict 전에 관찰되지 않았는지 검사한다.

### 야간·수동 확률 층

- Promptfoo `ko` red-team을 관련 plugin에만 제한하고 공격 생성 seed/config와 grader 모델 snapshot을
  기록한다. cache는 안전 퇴행을 숨기지 않도록 끄거나 run별로 분리한다.
- garak은 jailbreak/prompt-injection/encoding 등 gardevoir 위협모델과 맞는 probe만 선별하고
  generations 2 이상으로 시작한다. 전체 default 8만+ 호출은 CI에 부적합하다.
- 결과는 raw JSONL/JUnit, target commit, policy version, model snapshot, 비용, 총 호출 수와 함께
  artifact로 남긴다. 최초 baseline 대비 새 hit, 고위험 hit, over-block 증가에 자체 threshold를
  적용한다.
- 한국어 동적 결과는 자동 점수만으로 release를 막지 말고 사람 triage로 corpus에 승격한 뒤 다음
  PR부터 결정적 회귀 사례로 만든다.

## 확인 필요 목록

1. gardevoir ④가 요청의 OpenAI `tools[].function.parameters` JSON Schema를 현재 보존·검증하는지.
2. tool result가 승인된 tool-call ID/name과 강하게 연결되고 provenance를 위조할 수 없는지.
3. Guardrails AI streaming generator가 각 validator/OnFail 조합에서 검증 전 원문을 호출자에게
   내보내는 정확한 순서. 공식 문서만으로 비누출을 증명할 수 없다.
4. NeMo의 한국어 지원 모델별 실제 목록과 한국어 input/output/retrieval benchmark.
5. Promptfoo adaptive strategy별 정확한 attacker/target/grader 호출 상한과 retry 포함 비용식.
6. garak 현재 고정 버전의 JSONL schema 안정성, detector별 한국어 가능 여부, 실패 threshold의
   공식 process exit contract.
7. gardevoir 저장소 자체 라이선스. 조사 시점 작업 트리에서 `LICENSE*` 파일을 찾지 못했다.
8. 128자 holdback/512자 overlap이 한국어·Unicode·긴 간접 프롬프트 인젝션에서 만드는 FN/TTFT
   trade-off. 현재 §9의 정규식 누출 실측만으로 모델 rail까지 일반화할 수 없다.

## 주요 공식 출처

### NeMo Guardrails

- [Rail types](https://docs.nvidia.com/nemo/guardrails/latest/about-nemo-guardrails-library/rail-types)
- [Runtime security FAQ](https://docs.nvidia.com/nemo/guardrails/resources/runtime-security-faq)
- [Guardrails configuration, parallel and speculative generation](https://docs.nvidia.com/nemo/guardrails/configure-guardrails/yaml-schema/guardrails-configuration)
- [Output rail streaming](https://docs.nvidia.com/nemo/guardrails/configure-guardrails/yaml-schema/streaming/output-rail-streaming)
- [Rail engine support](https://docs.nvidia.com/nemo/guardrails/reference/rail-engine-support)
- [Model memory cache](https://docs.nvidia.com/nemo/guardrails/latest/configure-guardrails/caching/model-memory-cache)
- [2023 EMNLP demo paper](https://aclanthology.org/2023.emnlp-demo.40.pdf)
- [Repository and Apache-2.0 license](https://github.com/NVIDIA-NeMo/Guardrails)

### Guardrails AI

- [Validators](https://guardrailsai.com/guardrails/docs/concepts/validators)
- [Error and remediation](https://guardrailsai.com/guardrails/docs/concepts/error_remediation)
- [Performance](https://guardrailsai.com/guardrails/docs/concepts/performance)
- [Streaming](https://guardrailsai.com/guardrails/docs/concepts/streaming)
- [Core repository license](https://github.com/guardrails-ai/guardrails/blob/main/LICENSE)
- [Server license](https://github.com/guardrails-ai/guardrails-api/blob/main/LICENSE)

### OpenAI Guardrails Python

- [Quickstart and stage/tool behavior](https://openai.github.io/openai-guardrails-python/quickstart/)
- [Streaming vs blocking](https://openai.github.io/openai-guardrails-python/streaming_output/)
- [Jailbreak benchmark](https://openai.github.io/openai-guardrails-python/ref/checks/jailbreak/)
- [Prompt Injection benchmark and tool checks](https://openai.github.io/openai-guardrails-python/ref/checks/prompt_injection_detection/)
- [Hallucination Detection](https://openai.github.io/openai-guardrails-python/ref/checks/hallucination_detection/)
- [Contains PII](https://openai.github.io/openai-guardrails-python/ref/checks/pii/)
- [Repository and MIT license](https://github.com/openai/openai-guardrails-python)

### 모델·PII·평가 도구

- [Llama Guard 4 12B model card and license](https://huggingface.co/meta-llama/Llama-Guard-4-12B)
- [Granite Guardian 4.1 8B model card](https://huggingface.co/ibm-granite/granite-guardian-4.1-8b)
- [Presidio Anonymizer](https://presidio.dataprivacystack.org/anonymizer/)
- [Presidio supported entities](https://github.com/data-privacy-stack/presidio/blob/main/docs/supported_entities.md)
- [Presidio default recognizers](https://raw.githubusercontent.com/data-privacy-stack/presidio/main/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml)
- [Promptfoo OpenAI-compatible provider](https://www.promptfoo.dev/docs/providers/openai/)
- [Promptfoo red-team configuration and languages](https://www.promptfoo.dev/docs/red-team/configuration/)
- [Promptfoo CI/CD](https://www.promptfoo.dev/docs/integrations/ci-cd/)
- [garak OpenAI-compatible generator](https://github.com/NVIDIA/garak/blob/main/garak/generators/openai.py)
- [garak acceleration](https://reference.garak.ai/en/latest/faster.html)
- [garak translation limitations](https://reference.garak.ai/en/latest/translation.html)
- [garak repository and license](https://github.com/NVIDIA/garak)
