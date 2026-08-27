# 마스킹 위치 특정(localizer) 모델 조사

> 조사일: 2026-08-27 (KST)
> 범위: 공개 모델 카드·논문·공식 문서의 라이브 확인, 기존 GB10 실측 재검토, 실행 중인
> Qwen3-VL-8B-Instruct와 Shieldstral-1.0-3B에 대한 읽기성 추론
> 수행하지 않은 것: gardevoir 코드 변경, 모델 다운로드, 새 모델 서빙, 컨테이너/추론 설정 변경

## 0. 결론

### 짧은 답

1. **판정과 span을 함께 내는 공개 모델은 존재한다.** 2026년의
   [GLiNER Guard Omni](https://huggingface.co/hivetrace/gliner-guard-omni)는 한 encoder
   forward에서 `safe/unsafe`와 PII 인용 문자열을 함께 내며,
   [REMEDy](https://link.springer.com/article/10.1007/s00521-026-12381-9)는 전역 판정과
   span rationale을 함께 학습하는 연구를 보였다. 따라서 “그런 모델이 전혀 없다”는 결론은
   더 이상 맞지 않는다.
2. 그러나 **한국어를 필수로 하는 gardevoir에 바로 투입할 수 있다고 검증된 통합 모델은 없다.**
   GLiNER Guard의 multilingual은 기반 모델의 zero-shot 주장일 뿐 한국어 학습·평가가 없고,
   Fastino 통합 모델은 지원 언어를 유럽 7개 언어로 명시한다. REMEDy는 단일 언어 연구이며
   바로 받을 수 있는 fine-tuned checkpoint도 확인되지 않았다.
3. **Nemotron Safety Guard의 JSON에는 evidence span이 없다.** 공식 모델 카드가 정의한 필드는
   `User Safety`, `Response Safety`, `Safety Categories` 세 가지뿐이다. JSON이라는 이유로
   인용이나 offset이 있을 것이라고 추정하면 안 된다.
4. 현재 선택은 **Shieldstral 판정 → 필요한 경우에만 별도 Localizer**인 2-stage가 맞다.
   Shieldstral의 빠르고 안정적인 판정을 버릴 한국어 근거가 아직 없고, MASK 요청에만 위치 특정
   비용을 지불할 수 있다.

### 권고 순위

| 순위 | 권고 | 이유 | 현재 상태 |
| --- | --- | --- | --- |
| 1 | **Presidio의 한국 식별자/카드 규칙을 빠른 경로로 쓰고, 찾지 못한 이름·주소·계좌·동적 policy는 이미 상주한 Qwen3-VL-8B를 Localizer fallback으로 재사용** | 새 모델 메모리가 0이고, 한국어 주민번호·카드번호 인용을 guided JSON으로 7/7 정확히 복사했다. 주민번호·카드처럼 형식 검증 가능한 값은 생성 모델보다 regex/checksum을 먼저 쓰는 편이 안전하다. | **구조 권고**. Qwen 표본은 한 문장뿐이고 p50이 3.36초이므로 production 승인 전 자체 corpus 평가가 필요하다. |
| 2 | **`ehd0309/ko-pii-public-v1` v4 + Presidio를 Qwen fallback의 대체 후보로 비교 평가** | 한국어 23종에 이름·주소·주민번호·계좌·카드를 모두 포함하고, GB10에서 학습됐으며 제작사 KDPII 평가가 있다. autoregressive 생성이 아닌 token classification이다. | **평가 후보**. 2.8 GB checkpoint, CC BY-SA 4.0, 개인 배포/SLA 없음, 자체 실측 없음. 라이선스·정확도·지연 검증 전 배포 금지. |

0.2~0.3B GLiNER 계열은 메모리 면에서는 가장 좋지만 **한국어 필수 조건 때문에 지금의 1·2순위가
아니다.** 한국어 일반 NER에서 공개된 비교치는 `gliner_multi` F1 37.26이고, PII 전용 checkpoint는
한국어를 학습·평가하지 않았다. 작은 모델을 선택하고 나중에 한국어가 되기를 기대하는 것은 이
조사의 안전 기준과 맞지 않는다.

또한 위 순위는 “오늘 바로 production에 승인된 모델” 순위가 아니다. **현재 production-ready로
판정할 수 있는 후보는 0개**이며, 검증 순서에 대한 권고다.

### 근거 표기

- **실측**: 이 GB10에서 직접 관찰한 값
- **공식**: 공식 모델 카드·프로젝트 문서에 적힌 사실
- **제작사 평가**: 후보 제작자가 자기 데이터/방법으로 보고한 수치
- **추정**: 실제 GB10 측정 전 용량 계획을 위한 가설
- **판단**: 위 사실을 gardevoir의 계약에 적용한 결론

## A. 판정과 span을 한 모델에서 낼 수 있는가

### A.1 Nemotron JSON 확인: span 없음

[NVIDIA Llama-3.1-Nemotron-Safety-Guard-8B-v3 모델 카드](https://huggingface.co/nvidia/Llama-3.1-Nemotron-Safety-Guard-8B-v3)는
출력을 다음 세 필드로 한정한다.

```json
{
  "User Safety": "safe | unsafe",
  "Response Safety": "safe | unsafe (optional)",
  "Safety Categories": "comma-separated category names (optional)"
}
```

`evidence`, `span`, `quote`, `start`, `end`는 모델 카드의 output contract와 예제 어느 쪽에도 없다.
따라서 Nemotron의 JSON은 **taxonomy가 구조화된 것**이지 **위치가 구조화된 것**이 아니다.

추가 제약도 gardevoir에는 불리하다.

- 크기: 8.03B, BF16
- 라이선스: NVIDIA Open Model License + Llama 3.1 조건
- 언어: 학습 지원 9개 언어에 한국어가 없다. 한국어는 “20개 이상 zero-shot” 목록에만 있다.
- 공식 integration: NeMo 24.12, H100/A100. GB10/aarch64 지원은 카드에 없다.

즉 Nemotron은 Shieldstral의 판정 대체 후보일 수는 있어도 마스킹 위치를 해결하지 않는다.

### A.2 실제 통합 후보

| 후보 | 크기·라이선스 | 판정 + 위치 출력 | 한국어 | 서빙/가용성 | 결론 |
| --- | --- | --- | --- | --- | --- |
| [hivetrace/gliner-guard-omni](https://huggingface.co/hivetrace/gliner-guard-omni) | HF 표기 0.3B/F32, 카드 본문 307M; 논문은 Omni 209M으로 서로 달라 실제 revision 확인 필요. Apache-2.0 | 같은 `model.extract` schema에 classification과 entities를 넣는다. 카드 예제는 `safety: unsafe`와 `entities: {email: [...]}` 인용 문자열을 한 번에 반환한다. | 기반 multilingual DeBERTa-v3의 zero-shot 보존 주장. 카드 tag는 English/Russian이고 한국어 학습·평가 없음. | GLiNER2/PyTorch. vLLM 모델이 아니며 공개 inference provider 없음. GB10/aarch64 실측 없음. | **존재 증명**, 한국어 운영 후보는 아님 |
| [fastino/GLiNER2-Guardrails-PII-Multi](https://huggingface.co/fastino/GLiNER2-Guardrails-PII-Multi) | HF 0.3B/F32, Apache-2.0 | 한 checkpoint가 safety 분류와 42종 PII span을 모두 지원한다. 다만 공식 “combined pipeline” 코드는 `classify_text` 뒤 `extract_entities`를 따로 호출한다. “single deployment”는 확인되지만 **한 forward라는 추정은 하지 않는다.** | 명시 지원 EN/FR/ES/DE/IT/PT/NL. 비유럽 locale/script는 측정하지 않았다고 카드가 밝힌다. | GLiNER2/PyTorch, CPU/GPU. 공개 provider 없음. | 한국어 실격 |
| [GLiNER Guard 논문](https://arxiv.org/abs/2605.05277) | compact 145~147M, Omni 209M | safety classification과 PII detection을 한 forward로 수행한다고 논문이 명시한다. | 논문 초록에 한국어 결과 없음 | 제작사 A100 dynamic batching: compact 193 req/s, p99 < 1s. GB10 단건 지연으로 환산 불가 | 통합 encoder 계열의 근거 |
| [REMEDy 논문](https://link.springer.com/article/10.1007/s00521-026-12381-9) / [repo](https://github.com/leonardoPiano/REMEDy) | Llama-3.2-3B, Llama-3.1-8B, Mistral-7B, Gemma2-9B fine-tuning. repo MIT이나 기반 모델 조건은 별도 | 한 출력에서 `Malicious/Doubtful/Benign` 전역 label과 structured span rationale을 함께 생성하는 joint task | 논문이 monolingual limitation과 multilingual future work를 명시 | 학습·평가 code/data/output은 있으나, 조사 시점 repo/HF에서 바로 서빙할 완성 checkpoint는 확인하지 못함 | 연구 근거, 배포물 아님 |

REMEDy는 기존 guardian의 coarse label 한계를 정확히 다루며, 21개 category의 겹치거나 중첩된
span rationale을 학습한다. 다만 “논문에서 fine-tune했다”와 “재사용 가능한 모델을 공개했다”는 다른
사실이다. 현재 repo는 `train.py`, GLiNER/NuNER 학습 script와 평가 output을 제공할 뿐 완성 모델
checkpoint를 배포하지 않는다.

### A.3 A의 결론

- **존재 여부**: 예. 통합 encoder checkpoint와 generative joint-task 연구가 있다.
- **한국어 production 후보 존재 여부**: 확인하지 못했다.
- **Shieldstral 즉시 대체 여부**: 아니오. 통합 모델의 한국어 policy 판정과 PII exact-span recall을
  같은 corpus에서 동시에 통과시킨 근거가 없다.
- **Nemotron evidence span 여부**: 명확히 아니오.

## B. 위치 특정 전용 후보

### B.1 Zero-shot/span NER 계열

| 후보 | 확인한 크기 | 언어·한국어 근거 | 라이선스 | 출력 형태 | 서빙과 GB10 판단 |
| --- | ---: | --- | --- | --- | --- |
| [urchade/gliner_multi-v2.1](https://huggingface.co/urchade/gliner_multi-v2.1) | 공식 표 209M; HF metadata 0.3B/F32 | multilingual. 다만 한국어 KONNE dev 외부 비교에서 F1 37.26 | Apache-2.0 | `predict_entities`가 `text`, `label`, `start`, `end`, `score`를 반환. 인용 문자열 있음 | GLiNER/PyTorch, 공식 [Ray Serve](https://github.com/urchade/GLiNER/blob/main/docs/serving.md) HTTP 지원. vLLM 아님. arm64/GB10 실측 없음 |
| [urchade/gliner_multi_pii-v1](https://huggingface.co/urchade/gliner_multi_pii-v1) | 위 209M 기반, repo 1.16 GB F32 weight | synthetic PII 6개 언어. 주민번호라는 일반 label은 있으나 한국 형식 학습·평가 없음 | Apache-2.0 | `text` quote + label/offset/score | 가장 직접적인 소형 PII 후보지만 한국어 승인 불가 |
| [fastino/gliner2-privacy-filter-PII-multi](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi) | 카드 205M, HF 0.3B/F32 | EN/FR/ES/DE/IT/PT/NL, non-European 미측정 | Apache-2.0 | quote 문자열과 선택적 confidence/offset. 카드 redaction 예제도 `text.find(value)` 사용 | GLiNER2/PyTorch. 제작사 SPY exact-span 평균 F1 0.477, recall 0.718. synthetic 4,910개뿐이며 한국어 실격 |
| [nvidia/gliner-PII](https://huggingface.co/nvidia/gliner-PII) | 570M, 목표 상한을 조금 넘음 | 모델 카드 language tag English, 한국어 결과 없음 | NVIDIA Open Model License | `{text,label,start,end,score}`로 quote 직접 제공 | PyTorch/GLiNER. Blackwell GPU 지원은 명시하지만 CPU는 x86_64만 명시; GB10의 arm64 host 조합은 확인 필요. 제작사 strict F1: Argilla 0.70, AI4Privacy 0.64, synthetic Nemotron 0.87 |
| [numind/NuNER_Zero-span](https://huggingface.co/numind/NuNER_Zero-span) | repo F32 weight 1.8 GB, 약 0.4~0.5B급 | 카드가 English로 명시 | MIT | GLiNER API의 quote span. 12 token보다 긴 entity를 탐지하지 못한다고 카드가 명시 | 한국어 실격. 오래된 `gliner==0.1.12` 요구도 운영 부담 |
| [taeminlee/gliner_ko](https://huggingface.co/taeminlee/gliner_ko) | repo F32 weight 1.21 GB, 약 0.3B급 | Korean 전용. 제작사 KONNE dev P/R/F1 = 72.51/79.82/75.99 | **CC BY-NC 4.0** | GLiNER quote span | 일반 한국어 NER baseline으로 유용하지만 상업 사용과 PII taxonomy가 모두 맞지 않음 |

GLiNER의 크기 외에 중요한 운영 함정은 **긴 입력의 조용한 prefix 손실**이다. 공식
[input limit 문서](https://github.com/urchade/GLiNER/blob/main/docs/input_limits.md)에 따르면
`config.max_len`을 넘는 입력은 경고만 내고 prefix만 처리하며, 반환값에는 truncation 표시가 없다.
HTTP 200과 정상 모양의 span이 와도 뒤쪽 PII는 모델에 들어가지 않았을 수 있다. 따라서 다음은
선택 사항이 아니라 fail-closed 조건이다.

- 입력 token 수를 model의 public preparation API로 먼저 확인한다.
- 초과하면 overlap window로 모두 처리한다. span model의 overlap은 최소 `max_width - 1` token이다.
- 모든 window가 성공했는지 확인하고 offset을 문서 좌표로 옮긴 뒤 중복을 병합한다.
- window 누락, timeout, truncation 불명확성은 MASK가 아니라 BLOCK이다.

공식 GLiNER serving은 Ray Serve이며 응답에 `text` 인용을 포함한다. 기본 설정의
`target-memory-fraction=0.9`를 이 통합 메모리 장비에서 그대로 쓰면 안 된다. 실제 배포 실험에서는
명시적으로 작은 상한을 주고 시스템 `MemAvailable`과 swap-out을 함께 봐야 한다.

### B.2 Presidio와 규칙/checksum 파이프라인

[Presidio의 현재 supported entities 문서](https://github.com/data-privacy-stack/presidio/blob/main/docs/supported_entities.md)는
한국 항목을 별도로 제공한다. 예전 조사 결과를 그대로 재사용하면 안 되는 부분이다.
[기본 recognizer 설정](https://github.com/data-privacy-stack/presidio/blob/main/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml)은
한국 recognizer의 `ko`/`kr` 언어와 기본 비활성을 확인시켜 주며,
[changelog](https://github.com/data-privacy-stack/presidio/blob/main/CHANGELOG.md)는 RRN을 2.2.360,
나머지 네 종류를 2.2.361에 추가한 이력을 남긴다.

| gardevoir 필요 항목 | 현재 Presidio 지원 | 주의점 |
| --- | --- | --- |
| 주민등록번호 | **내장 `KR_RRN` 있음**. pattern/context/custom logic. 2.2.360 changelog는 2020년 10월 이전 번호의 checksum 검증을 명시 | 기본 registry에서 `enabled: false`; `ko`/`kr` 언어로 명시 활성화해야 한다. 2020년 이후 random serial은 checksum으로 기각하면 안 된다. |
| 외국인등록번호·사업자번호·운전면허·여권 | **`KR_FRN`, `KR_BRN`, `KR_DRIVER_LICENSE`, `KR_PASSPORT` 내장** | 2.2.361에 추가됐고 모두 기본 비활성이다. 법인등록번호 `KR_CRN`은 아직 [공개 issue](https://github.com/data-privacy-stack/presidio/issues/2177) 단계라 내장이라고 보면 안 된다. |
| 카드번호 | 전역 `CREDIT_CARD`가 regex + Luhn checksum 지원 | 기본 YAML 언어는 en/es/it/pl이다. class는 `supported_language`와 context를 받으므로 `ko` instance와 `카드`, `신용카드` context를 명시해야 한다. 숫자 모양만으로는 base score가 낮다. [구현 source](https://github.com/data-privacy-stack/presidio/blob/main/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/credit_card_recognizer.py) |
| 한국 계좌번호 | **내장 없음**. 전역 `IBAN_CODE`는 한국 국내 계좌번호가 아니다. | 은행별 길이·구분자가 달라 단일 regex만으로 production recall/precision을 주장할 수 없다. custom recognizer + 한국어 PII model/Qwen 보완 필요 |
| 전화번호 | `PhoneRecognizer`의 region 설정 가능 | `KR` region과 한국어 context로 별도 구성·평가 필요 |
| 한국 이름·주소 | Presidio의 generic `PERSON`/`LOCATION`은 NLP engine에 의존 | 한국어 NER model을 연결하지 않으면 “한국 이름/주소 지원”이라고 볼 수 없다. Presidio는 Transformers·GLiNER recognizer 연결을 공식 지원한다. |

Presidio `RecognizerResult`는 `entity_type`, `start`, `end`, `score`만 제공하므로 **인용 문자열을
직접 주는 후보는 아니다.** adapter가 원문 `text[start:end]`를 잘라 quote를 만들고, pattern/checksum과
원문 exact-find를 다시 통과시켜야 한다. application port에는 Presidio offset을 노출하지 않는다.

Presidio의 장점은 모델 하나가 아니라 **regex + checksum + NER + custom recognizer를 합치는
framework**라는 점이다. 숫자 식별자는 이 경로가 Qwen보다 빠르고 설명 가능하다. 반대로 프로젝트
자체도 모든 민감 정보를 찾는다는 보장은 없다고 밝히므로, 이름·주소·계좌까지 Presidio 기본값 하나로
해결됐다고 간주하면 안 된다.

### B.3 이미 상주한 일반 instruct 모델 재사용

#### 구조화 출력 방법

[vLLM structured outputs 공식 문서](https://docs.vllm.ai/en/latest/features/structured_outputs/)의
현재 계약은 다음 두 가지다.

- OpenAI-compatible `response_format={"type":"json_schema", ...}`
- `extra_body={"structured_outputs":{"json": schema}}`

예전 `guided_json` 필드는 deprecated된 뒤 vLLM 0.12.0에서 제거됐다. 현재 Qwen server는
`/version` 실측상 vLLM 0.21.0이고 `response_format` JSON Schema를 실제로 받아들였다. 따라서 새
설계 문서나 adapter가 `guided_json`이라는 과거 필드명에 고정되면 안 된다.

JSON Schema가 강제할 수 있는 것은 `quotes: string[]`, item 수, 추가 field 금지 같은 **문법**이다.
“각 string이 원문에 있고, 요청한 entity type이며, 최소 substring이고, 모든 PII를 빠짐없이
포함한다”는 의미 제약은 표현하지 못한다.

#### 2026-08-27 로컬 실측

조건:

- 실행 중 container와 설정은 변경하지 않았다.
- gardevoir gateway container에서 `python urllib`로 내부 DNS
  `qwen3-vl-8b-instruct:8000`에 순차 요청했다.
- source: 한국어 한 문장, 주민번호 `801209-1234567`, 카드번호
  `4321-8765-1234-9999` 포함
- temperature 0, max tokens 64, JSON Schema `{"quotes": [string, ...]}`
- 엄격한 prompt: entity type 두 개를 명시하고, 최소·연속·원문 그대로인 값만 복사하도록 요구

결과:

```json
{"quotes": ["801209-1234567", "4321-8765-1234-9999"]}
```

7회 모두 byte-for-byte 같은 JSON이었다. 전체 HTTP wall time은 p50 **3,361.8 ms**,
p95 nearest-rank **3,393.7 ms**였다. 7개 표본은 `[3294.3, 3354.3, 3358.3, 3393.7,
3382.4, 3384.6, 3361.8] ms`다.

반면 entity type과 최소성 지시가 약한 첫 probe에서는 schema를 완벽히 지키면서 다음처럼 **원문
전체**를 하나의 quote로 냈다.

```json
{
  "quotes": [
    "고객 김민수의 주민등록번호는 801209-1234567이고 카드번호는 4321-8765-1234-9999입니다. 오늘 간식은 사과입니다."
  ]
}
```

이 값도 원문 `find`에는 성공한다. 따라서 exact-find는 환각을 막는 **필요조건**이지만 최소성·정확한
종류·누락 없음의 충분조건은 아니다. 지나치게 넓은 quote는 전부 가리므로 privacy fail-open은 아니지만
서비스 의미를 파괴한다. 길이 비율 상한을 넘으면 BLOCK하는 편이 낫다.

[Qwen3-VL-8B-Instruct 카드](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)는
Apache-2.0과 8B 모델, OCR 32개 언어를 명시하지만 한국어 PII 성능을 제시하지 않는다. 위 한 문장
7회는 **생성 안정성** 실측이지 한국어 recall 평가가 아니다.

Qwen 재사용의 trade-off는 다음과 같다.

- 장점: 새 weight/engine 메모리 0, 임의 policy/entity type, 원문 quote 직접 생성, 이미 GB10/aarch64와
  vLLM에서 동작 확인
- 단점: 이 짧은 예제도 약 3.36초, Qwen 본래 요청과 queue/KV cache 공유, prompt 민감성, 존재하는
  엉뚱한 문자열 인용과 누락 가능
- 안전 판단: 빠른 규칙/NER이 못 찾은 MASK에서만 fallback으로 쓰고, schema 성공만으로 마스킹하지 않는다.

### B.4 한국어 PII 특화 후보

#### 가장 근거가 많은 후보: `ehd0309/ko-pii-public-v1` v4

[모델 카드](https://huggingface.co/ehd0309/ko-pii-public-v1)가 명시한 범위는 gardevoir 요구와 가장
가깝다.

- 23종: `person_name`, `address`, `rrn`, `bank_account`, `card_number`를 모두 포함하며 전화·email,
  공공·의료 식별자도 포함
- Transformers token classification, BIO 47 labels; pipeline 결과에서 원문 `word` span을 만들 수 있음
- repository 2.83 GB, 그중 safetensors 2.8 GB
- HF metadata는 1B, 카드 본문은 base를 1.5B total/50M active MoE라고 적어 표기가 다르다. 용량
  계산에는 실제 2.8 GB file을 쓴다.
- v4 라이선스 CC BY-SA 4.0. 이전 v2 commit은 Apache-2.0이지만 long-document 개선과 KLUE NER가 없다.
- 제작사 KDPII held-out, threshold 0.93의 v4 F1 0.860. 단일 seed, lenient overlap span metric이다.
- long-document 수치는 대부분 training template와 가까운 synthetic 평가라 절대값을 일반화하면 안 된다.
- 카드가 직접 naked passport/vehicle miss, 자체 production data 없음, 긴 입력 chunking 필요를 제한으로
  적는다.
- 1× GB10 BF16으로 학습했다는 사실은 확인되지만 **GB10 inference latency/메모리 실측은 아니다.**

모델 카드가 regex fallback과 200자 안팎 chunking을 스스로 권고한다는 점도 “모델 단독”보다
Presidio/규칙과의 hybrid가 맞다는 근거다.

#### 더 작은 공개 후보

| 후보 | 크기·라이선스 | 지원 | 근거 수준과 결론 |
| --- | --- | --- | --- |
| [seungkukim/korean-pii-masking](https://huggingface.co/seungkukim/korean-pii-masking) | 0.1B/F32, MIT | 이름, 전화, email, 주민번호, 카드 | 매우 작고 quote 가능한 token classifier지만 계좌·주소가 없고 training/eval metric과 model provenance가 카드에 없다. 보조 probe 후보일 뿐 2순위보다 근거가 약하다. |
| [alphagyuu/Korean-PII-Masking-BertForTokenClassification](https://huggingface.co/alphagyuu/Korean-PII-Masking-BertForTokenClassification) | KcBERT-base/TensorFlow, Apache-2.0 | URL·계정·금융·번호·소속·신원·이름·주소의 coarse label | AI-Hub Korean SNS 가공 학습이라고 하나 metric과 주민번호/카드/계좌의 분리 label이 없다. 운영 policy mapping이 모호하다. |
| [mncai/Korean-PII-Masking-Model](https://huggingface.co/mncai/Korean-PII-Masking-Model) | KcBERT-Large, license metadata 없음 | 계좌·상세주소·여권·면허·이름·email·전화·주민번호·카드 등 | label 범위는 좋지만 checkpoint download/provider/평가/라이선스가 확인되지 않는다. 후보 탈락. |
| `taeminlee/gliner_ko` | B.1 참조 | 한국어 general NER | F1 근거는 있으나 non-commercial이고 한국 PII identifier 학습 근거가 없다. 연구용 baseline만 가능. |

## C. gardevoir 제약에 맞춘 권고

### C.1 GB10 통합 메모리 예산

기준은 기존 [Shieldstral hosting 실측](./2026-08-27-shieldstral-hosting.md)이다.

| 항목 | hosting 문서 최종 실측 | 이 조사 중 재확인 |
| --- | ---: | ---: |
| Qwen3-VL-8B checkpoint / 실제 model load | 16.33 / 16.65 GiB | 재기동하지 않음 |
| Qwen NVIDIA process allocation | 28,583 MiB | 28,583 MiB |
| Shieldstral allocation | 15,971 MiB | 15,971 MiB |
| BGE-M3 allocation | 1,633 MiB | 1,633 MiB |
| 세 engine 합계 | 46,187 MiB (45.10 GiB) | 동일 |
| system `MemAvailable` | 55 GiB | 53 GiB |
| swap | 6.2 GiB, 10초 `so=0` | 6.1 GiB, interval 표본 `so=0` |

Qwen의 16.65 GiB **model load**와 28,583 MiB **engine process allocation**은 다른 값이다.
localizer를 추가할 때는 weight 크기만 보지 않고 runtime graph/activation/allocator와 시스템
`MemAvailable`을 봐야 한다.

0.3B dense encoder의 weight-only 하한은 다음과 같다.

| dtype | 계산 | weight-only |
| --- | ---: | ---: |
| BF16/FP16 | 300,000,000 × 2 bytes | 0.559 GiB |
| FP32 | 300,000,000 × 4 bytes | 1.118 GiB |

이는 현재 `MemAvailable` 53 GiB의 각각 **1.05%, 2.11%**이고, 세 engine 할당 합계의
1.24%, 2.48%다. tokenizer, activation, framework, Ray process와 CUDA graph를 더한 실제 증분은
아직 모르지만, **weight 관점에서 0.3B localizer가 부담이 거의 없다는 판단은 수치로 성립한다.**

다른 선택의 메모리 판단은 다음과 같다.

- Qwen 재사용: weight/engine 증분 0. 다만 동시 요청 시 기존 28,583 MiB engine의 KV/queue와
  처리량을 공유한다.
- `ko-pii-public-v1`: 실제 repo 2.8 GB weight, 약 2.61 GiB. 53 GiB available에는 들어가지만
  runtime 증분을 직접 재야 한다.
- Presidio numeric recognizer: 모델 weight 없음. 한국 이름/주소 NER를 연결하면 그 model 비용은 별도다.
- 570M NVIDIA GLiNER: BF16 weight-only 약 1.06 GiB, FP32 약 2.12 GiB. 역시 용량 자체보다 한국어
  정확도가 먼저 막힌다.

30B Qwen 시절 세 engine 89,179 MiB와 `MemAvailable` 15~16 GiB였던 구성과 달리 지금은 localizer
실험 여유가 충분하다. 그러나 swap 6 GiB가 이미 사용 중이므로 이를 추가 예산으로 계산하지 않는다.

### C.2 지연: 실측과 추정 분리

| 단계/후보 | p50 | p95 | 근거 |
| --- | ---: | ---: | --- |
| Shieldstral localizer prompt | 121.4 ms | 174.6 ms | **실측**, n=7 순차, 결과는 모두 `yes`; 위치는 못 냄 |
| Qwen guided JSON localizer | 3,361.8 ms | 3,393.7 ms | **실측**, n=7 순차, 같은 짧은 한국어 문장, 42 completion tokens. nearest-rank라 안정적인 production percentile이 아님 |
| 0.2~0.3B encoder | 20~100 ms | 50~250 ms | **추정**, 짧은 입력·warm·concurrency 1의 용량 계획 범위. GB10 측정 전 약속값이 아님 |
| `ko-pii-public-v1` | 30~150 ms | 100~400 ms | **추정**, one-forward token classifier라는 구조와 2.8 GB weight만 반영한 넓은 범위 |
| Presidio regex/checksum only | < 5 ms | < 10 ms | **추정/목표**, NER engine과 HTTP 제외 |

GLiNER Guard 논문의 A100 193 req/s 및 p99 < 1s는 dynamic batching 조건의 제작사 수치다. GB10
단건 p50/p95로 변환하지 않았다.

2-stage의 평균 추가 지연은 대략 다음과 같다.

```text
전체 요청 평균 추가 지연 ≈ P(MASK 판정) × localizer 지연
MASK가 실제 발생한 요청의 추가 지연 = localizer 지연 전체
```

Qwen 경로는 MASK 비율이 낮아도 해당 요청에 약 3.4초를 추가한다. 따라서 숫자 식별자는 Presidio
fast path로 끝내고, Qwen은 동적 policy와 이름·주소·계좌처럼 규칙이 불충분한 경우로 좁혀야 한다.

### C.3 production 측정 방법과 승인 기준

현재 n=7 같은 동일 prompt 반복은 engine 동작 확인이지 품질/성능 승인이 아니다. 다음 순서로
후보를 같은 조건에서 측정한다.

1. 허가된 한국어 in-domain corpus를 최소 1,000건 준비한다. 주민번호·계좌·카드·주소·이름을 각각
   별도 집계하고, PII 없는 hard negative, separator/OCR/Unicode 변형, 같은 값 반복을 포함한다.
2. 128/512/2,048자 길이 bucket과 entity 0/1/다수 bucket을 교차한다. 긴 입력은 실제 windowing을
   포함하고, 한 window라도 빠진 사례를 성공으로 세지 않는다.
3. cold start와 warm path를 분리한다. warm-up 후 concurrency 1/4/8에서 각 1,000회 이상 측정한다.
4. wall clock은 HTTP serialize → inference → JSON parse → quote 검증 → mask 적용 → residual 검사까지
   포함한다. engine-only 시간과 end-to-end 시간을 따로 기록한다.
5. p50/p95/p99, throughput, queue time, timeout율과 함께 `MemAvailable`, NVIDIA process allocation,
   swap `si/so`, 기존 Qwen TTFT 회귀를 기록한다.
6. 품질은 average F1 하나로 승인하지 않는다. entity별 exact-span precision/recall, untyped recall,
   masked 결과의 잔존 PII율, 불필요하게 전체 BLOCK된 비율을 낸다. 주민번호·계좌·카드의 false
   negative는 별도 0-tolerance gate로 둔다.

시작 acceptance target은 다음처럼 두는 것이 합리적이다. 실제 SLO는 트래픽 측정 뒤 확정한다.

- numeric fast path: warm p95 ≤ 20 ms, canonical 주민번호/유효 카드 false negative 0
- learned small localizer: 512자 이하 warm p95 ≤ 250 ms
- Qwen fallback: 동시성 부하에서 p95 ≤ 5 s, timeout/invalid schema 0.1% 미만
- 어느 경로든 잔존 위반, truncation, quote 검증 실패 시 MASK 성공으로 집계하지 않고 BLOCK

### C.4 안전 계약: offset이 아니라 검증된 quote

`Localizer`가 어떤 구현이든 다음 계약을 바꾸지 않는다.

1. **모델 offset을 application contract에 넣지 않는다.** GLiNER/Transformers가 `start/end`를 함께
   줘도 adapter는 원문 quote만 넘긴다.
2. quote는 normalization, trim, case-fold를 하지 않은 원문에서 exact `find`한다. 한 글자라도 다르면
   전체 MASK를 실패시키고 BLOCK한다.
3. `violated=true`이고 action이 MASK인데 quote가 비어 있거나 localizer 결과가 누락되면 BLOCK한다.
4. 요청하지 않은 entity type, schema 위반, timeout, truncation, 일부 window 실패도 BLOCK한다.
5. 같은 quote가 원문에 여러 번 있으면 한 occurrence만 믿지 않고 **모든 literal occurrence를
   마스킹**한다. 서로 겹치는 span은 합치고 뒤에서 앞으로 적용한다.
6. quote가 원문 대부분/전체를 차지하는 등 최소성 상한을 위반하면 “성공한 마스크”로 취급하지 않고
   BLOCK한다. 이 규칙은 이번 Qwen weak-prompt 실측으로 필요성이 확인됐다.
7. 마스킹한 text를 형식 recognizer와 해당 policy judge로 한 번 다시 검사한다. 잔존 위반이면 추가
   생성 loop를 돌지 말고 BLOCK한다. exact-find만으로는 “엉뚱하지만 실제 존재하는 문구를 가리고
   PII는 남긴” 경우를 막지 못한다.
8. 원문 전체 coverage가 증명되지 않은 long-input 결과는 사용하지 않는다. GLiNER의 정상 HTTP 200은
   coverage 증명이 아니다.
9. dry-run에서는 quote와 최종 `would_have`를 계산하되 원문을 변경하지 않는다. audit에는 raw PII를
   별도 복제하지 않고 model/revision, type, 개수, 검증/실패 사유를 남긴다.

이 계약은 false negative를 없애지는 못한다. 그래서 residual judge와 deterministic recognizer가
필요하다. 모델 결과를 그대로 적용하는 것보다 **누락을 발견할 독립 경로**가 하나 더 있어야 한다.

## D. 아키텍처 권고

### D.1 2-stage 유지

권고 흐름은 다음과 같다.

```text
기존 rule tier
  ├─ 정확한 compiled regex span 있음 ───────────────▶ 즉시 MASK
  └─ model verdict 필요
       └─ Shieldstral ModelJudge
            ├─ ALLOW ───────────────────────────────▶ 통과
            ├─ BLOCK ───────────────────────────────▶ 차단
            └─ MASK
                 └─ Localizer
                      ├─ Presidio/checksum fast path
                      └─ Korean NER 또는 Qwen fallback
                           └─ quote exact-find + coverage + 적용
                                ├─ residual 없음 ───▶ MASK
                                └─ 그 밖의 모든 경우 ▶ BLOCK
```

| 관점 | 2-stage | 통합 모델 |
| --- | --- | --- |
| 현재 한국어 근거 | Shieldstral 판정과 Qwen quote를 각각 실측 | 통합 checkpoint의 한국어 판정+span 동시 평가는 없음 |
| 비용 | MASK일 때만 localizer 호출 | 모든 판정에 span head/추출 비용을 지불할 수 있음 |
| 장애 격리 | 판단 실패와 위치 실패를 따로 audit/fail-close | 한 모델 오류가 두 기능을 동시에 잃게 함 |
| policy 유연성 | Shieldstral natural-language policy 유지, localizer를 종류별 교체 | GLiNER 통합 모델은 학습 taxonomy/zero-shot 품질에 의존 |
| 향후 교체 | Localizer만 작은 한국어 모델로 교체 가능 | 검증을 통과하면 engine 하나로 단순화 가능 |

GLiNER Guard Omni 같은 통합 모델이 다음 조건을 모두 통과하면 Shieldstral 대체를 다시 논할 수 있다.

- 한국어 policy 판정이 현재 Shieldstral보다 열등하지 않음
- 주민번호·계좌·카드·주소·이름의 entity별 exact-span recall gate 통과
- arbitrary custom policy와 PII taxonomy를 동시에 처리
- GB10 concurrency p95와 memory 회귀 통과
- 인용 재검증/실패 시 BLOCK 계약 유지

현재는 이 조건을 만족했다는 자료가 없으므로 통합은 실험 track이지 설계 기본값이 아니다.

### D.2 `Localizer` 포트 제안

`ModelJudge`는 “위반인가”의 단일 소유자로 남기고, `Localizer`는 이미 내려진 MASK 판정의 “어디를
가릴 것인가”만 답한다. 위치 모델이 판정을 다시 소유하게 하지 않는다.

개념적 contract는 다음과 같다. 구현 코드는 이번 작업 범위가 아니다.

```text
LocalizeRequest
  checkpoint: input | tool_result | output | tool_call
  node_id: 판정 결과와 상관시킬 id
  policy: 원래 model node의 자연어 policy
  entity_types: 명시적으로 컴파일된 허용 종류 목록(없으면 빈 목록을 명시)
  text: 이 checkpoint에서 검사한 바로 그 원문
  deadline_ms: 남은 요청 예산

LocalizeResult
  node_id
  quotes: tuple[str, ...]          # offset 없음
  status: success | failed | truncated
  raw_status: 짧고 PII가 없는 진단 문자열

Localizer
  async localize(requests: Sequence[LocalizeRequest])
      -> Sequence[LocalizeResult]
```

설계 규칙:

- `quotes`는 string 배열이다. confidence와 model offset은 application이 마스크를 적용하는 근거가
  아니다. adapter 내부 관찰 metric으로는 보존할 수 있다.
- batch 순서가 아니라 `node_id`로 결과를 상관시킨다. missing/duplicate result는 실패다.
- `entity_types`는 node 설정/compiled plan에서 명시적으로 온다. wiring default로 임의 PII 목록을
  넣지 않는다.
- `Localizer`가 disabled인데 model MASK가 발생하면 현재처럼 BLOCK한다. `None` 기본값으로 조용히
  원문을 통과시키는 경로를 만들지 않는다.
- ModelJudge와 Localizer timeout을 분리하고, 전체 request deadline보다 각각 작게 제한한다.
- Qwen adapter는 JSON Schema를 쓰되 schema 성공을 quote 성공으로 번역하지 않는다.
- Presidio/GLiNER adapter는 source `text` field가 있으면 그것을 quote로 쓰고, offset만 있는 결과는
  원문 slice → type validator → exact-find를 거쳐 quote로 바꾼다.

### D.3 위치와 수명

기존 backend 구조에 맞춘 위치는 다음과 같다.

- port: `gateway/guardrail/application/port/localizer.py`
- MASK orchestration/검증: `gateway/guardrail/application/service/` 안의 model-tier 흐름
- HTTP/Presidio/GLiNER translation: `gateway/guardrail/infrastructure/adapter/`
- process-lifetime client/model 생성·종료: 유일한 composition root인 `gateway/app.py` lifespan
- request-lifetime 조립: `gateway/proxy/composition.py`
- 설정: `model_judge`와 별도인 `localizer.enabled/endpoint/model/revision/timeout_ms`

HTTP adapter는 자기 `AsyncClient`를 만들고 닫는다. app composition root가 `httpx`, Transformers,
Presidio driver를 직접 다루지 않는다. 요청 경로에 DB 조회를 추가하지 않으며, compiled plan에 필요한
entity type만 실어 둔다.

하나의 통합 model을 나중에 채택해도 **논리 port 둘은 유지**할 수 있다. 같은 infrastructure adapter가
두 protocol을 구현하거나 내부 combined result를 번역할 수 있지만, application에서 판정과 quote의
소유권을 다시 섞지는 않는다. 실제로 한 forward를 공유하려면 별도 combined adapter contract와
동시 한국어 검증이 먼저다. 이름만 통합하고 두 번 추론하는 최적화를 “single pass”라고 부르면 안 된다.

### D.4 현재 코드 범위에서의 rollout 주의

현재 `ModelTier.evaluate`는 proxy의 `_inspect_input_model`에서만 호출된다. 설정에는 checkpoint별
fail-mode가 있어도 output/tool_result/tool_call의 pending model을 같은 방식으로 resolve하는 경로는
아직 없다. 따라서 첫 Localizer rollout은 **input checkpoint**로 한정해 검증하는 것이 정직하다.

특히 streaming output은 이미 보낸 byte를 되돌릴 수 없다. 현재 Qwen localizer p95 약 3.4초는
128-char holdback 예산에 들어가지 않는다. 다음 중 하나를 별도 설계하기 전에는 streaming MASK를
지원한다고 하면 안 된다.

- 전체 output을 buffer한 뒤 localize해서 streaming 성질을 포기
- holdback 안에 드는 작은 localizer를 chunk/window coverage와 함께 사용
- 위치가 불확실한 streamed model MASK를 첫 byte 전에 BLOCK

## 미해결 및 다음 검증 목록

1. **한국어 자체 corpus**: 다섯 필수 종류별 exact-span recall/precision과 masked residual을 Qwen,
   `ko-pii-public-v1`, Presidio hybrid에서 같은 데이터로 비교해야 한다.
2. **라이선스**: `ko-pii-public-v1` v4의 CC BY-SA 4.0이 제품 배포에 주는 의무를 법무 확인해야 한다.
   불가하면 Apache-2.0 v2의 long-document 회귀를 별도로 평가한다.
3. **한국 계좌번호**: 은행별 format/keyword corpus와 custom validator 범위를 정해야 한다. Presidio
   내장 지원으로 잘못 기록하지 않는다.
4. **Presidio release pin**: 한국 recognizer가 들어간 실제 release를 고정하고 `enabled: false`,
   `ko`/`kr`, 한국어 card context 설정을 startup 검증해야 한다.
5. **GB10/aarch64**: GLiNER/GLiNER2/Ray Serve와 각 tokenizer/native dependency의 arm64 wheel 및
   CUDA 동작을 실제로 확인해야 한다. Blackwell 지원 표기만으로 host architecture를 추정하지 않는다.
6. **runtime memory**: 0.3B와 2.8 GB 후보의 process allocation, peak, `MemAvailable`, swap-out을
   모델별로 재야 한다. weight 계산은 runtime 실측이 아니다.
7. **Qwen contention**: localizer 호출 중 사용자 Qwen request의 TTFT/p95 회귀와 queue starvation을
   동시 부하로 측정해야 한다.
8. **긴 입력 coverage**: GLiNER와 Korean token classifier의 tokenizer/max_len, overlap, 중복 병합,
   모든 window 성공 증명을 adapter contract로 확정해야 한다.
9. **잔존 위반 검사**: masked text를 Shieldstral로 재판정했을 때의 false positive/latency를 측정하고,
   어떤 checkpoint에 적용할지 정해야 한다.
10. **통합 모델 한국어**: GLiNER Guard Omni/향후 multilingual checkpoint가 같은 acceptance corpus를
    통과할 때만 Shieldstral 대체 논의를 재개한다.

## 조사 중 보존한 로컬 상태

- 실행 container를 재시작·정지·변경하지 않았다.
- 모델, image, cache를 다운로드하거나 지우지 않았다.
- 조사 종료 시 Qwen3-VL-8B-Instruct, Shieldstral-1.0-3B, BGE-M3와 gardevoir service는 계속
  실행 중이다.
- 문서 외 gardevoir source/config는 변경하지 않았다.
