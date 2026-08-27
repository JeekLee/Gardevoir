# gardevoir 가드레일용 sLLM 조사

- 조사일: 2026-08-27 (KST)
- 범위: 로컬 서빙 여력, 가드 전용 sLLM, 이미지·문서 검사, 모델 티어 배선안
- 상태: 자료조사 완료. 모델 다운로드·설치·서빙 및 코드·스택 변경은 수행하지 않음

## 결론

gardevoir의 첫 모델 티어는 **텍스트 기준선으로 `Qwen3Guard-Gen-4B`**, 멀티모달 최종 후보로
**`Shieldstral-1.0-3B`**를 같은 HTTP 판정 포트 뒤에서 A/B 검증하는 것이 가장 현실적이다.
운영 기본값은 한국어·텍스트·이미지를 한 체크포인트에서 다루고 자연어 정책을 받아들이는
Shieldstral을 지향하되, 출시된 지 한 달이 안 된 모델이고 현재 호스트의 vLLM보다 새 버전을
요구하므로 Qwen3Guard를 먼저 텍스트 기준선으로 세운다.

두 모델을 지금 호스트에 동시에 상주시켜서는 안 된다. GB10의 메모리는 전용 VRAM과 시스템 RAM이
분리된 구조가 아니며, 조사 시점에 OS가 보고한 `available`은 약 31 GiB뿐이다. 기존
Qwen3-VL-30B-A3B와 BGE-M3 엔진의 NVIDIA 메모리 할당도 합계 약 70 GiB였다. 3~4B BF16 모델 한 개는
추가 실험이 가능해 보이지만, 이는 **용량 추정**일 뿐이다. 기존 부하와 함께 p95 지연, OOM, swap,
첫 요청 지연을 측정하기 전에는 상시 배치 가능하다고 결론 내릴 수 없다.

또한 가드 VLM은 이미지나 문서 전체를 `block`할 수는 있어도 주민번호 한 줄이나 얼굴을 정확히
찾아 픽셀 단위로 `mask`하는 도구가 아니다. 정밀 마스킹은 OCR·레이아웃/좌표 보존·PII 인식·얼굴 및
바코드 검출·실제 redaction·재검증 파이프라인이 필요하다. 위치 근거가 없는 의미 분류 결과는
`block` 또는 격리/승인으로만 사용해야 한다.

## 조사 방법과 증거 등급

로컬 조사는 읽기 전용 명령(`nvidia-smi`, `free -h`, `df -h`, `docker ps/inspect/stats`)만 실행했다.
컨테이너를 시작하거나 중지하지 않았고, 모델·패키지·이미지를 내려받지 않았다. 웹 자료는 2026-08-27에
라이브 확인했으며 다음 순서로 신뢰했다.

1. 제작사 모델 카드와 공식 서빙 문서
2. 원 논문과 여러 모델을 같은 조건에서 비교한 연구
3. Hugging Face 커뮤니티 리더보드

Hugging Face의 리더보드는 공식 평가 결과와 커뮤니티가 운영하는 Space가 섞인 구조다
([Hugging Face Leaderboards 문서](https://huggingface.co/docs/leaderboards/index)). 현재 실행 중인
[CircleGuardBench](https://huggingface.co/spaces/whitecircle/circle-guard-bench)도 커뮤니티 Space이므로,
그 순위를 제품 선택의 단독 근거로 쓰지 않았다. 모델 카드의 수치는 제작사 보고치이고 모델마다
프롬프트·임계값·데이터가 다르다. 이 문서에서 서로 직접 비교한 수치는 별도로 같은 평가를 수행한
논문만 사용한다.

## 1. 로컬 서빙 여력

### 1.1 조사 시점 상태

2026-08-27 11:06 KST 전후의 스냅샷이다. GB10은 통합 메모리 구조라서 `nvidia-smi`의 일반적인
`memory.total/used/free` 질의가 `N/A`였고, 아래 시스템 메모리와 GPU 프로세스 할당을 함께 봐야 한다.

| 항목 | 관측값 | 해석 |
| --- | --- | --- |
| GPU | NVIDIA GB10, driver 580.142, CUDA 13.0, GPU 사용률 2% | 사용률 2%는 순간값이라 용량 여유를 뜻하지 않는다. |
| CPU/아키텍처 | `aarch64`, 논리 CPU 20개 | 새 서빙 이미지도 ARM64/CUDA 조합을 확인해야 한다. |
| 시스템 메모리 | 총 121 GiB, 사용 90 GiB, free 2.5 GiB, available 31 GiB | 캐시 회수 가능분을 포함한 `available`이 실질적인 상한에 가깝다. |
| swap | 총 15 GiB, 사용 1.7 GiB | 모델 추론이 swap에 기대기 시작하면 지연과 안정성이 이미 실패한 상태다. |
| 루트 디스크 | 총 3.7 TiB, 사용 867 GiB, 여유 2.7 TiB | 저장 공간은 병목이 아니지만 이번 조사에서는 모델을 받지 않았다. |
| GPU 프로세스 | vLLM EngineCore 68,351 MiB + 1,633 MiB, 데스크톱 프로세스 약 2.3 GiB | 할당량은 실제 활성 working set과 같지 않지만 공존 여유를 판단하는 경고 지표다. |

실행 중인 관련 컨테이너도 확인했다.

| 컨테이너 | 조사 시점 설정 | 의미 |
| --- | --- | --- |
| `spark-inference-qwen3-vl-30b-a3b` | vLLM 0.21.0 ARM64/CUDA 이미지, `gpu-memory-utilization=0.60`, `max-model-len=32768` | 현재 주 생성/VLM 업스트림. GB10에서 vLLM 자체가 동작한다는 현장 증거다. |
| `spark-inference-bge-m3` | vLLM 0.19.1, `gpu-memory-utilization=0.05`, `max-model-len=8192` | 임베딩 엔진도 같은 통합 메모리를 사용한다. |
| `spark-inference-gateway` | `gardevoir-host:10080` 업스트림 | `/v1/models`는 인증 없이 조회할 수 없었으며 자격 증명은 조사하지 않았다. |
| gardevoir 서비스 | gateway, console, Postgres, ClickHouse, Redis | 모델 서버 외의 상시 메모리와 I/O도 남겨 두어야 한다. |

현재 Qwen3-VL-30B-A3B는 이미지도 이해하지만 생성 업스트림이지 가드 전용 분류기가 아니다. 같은
엔진을 자기 출력의 판정기로 재사용하면 생성과 안전 판정이 장애·용량을 공유하고, 전용 safety taxonomy와
임계값도 얻지 못한다. 별도 corpus에서 그 역할을 검증하기 전에는 “이미 VLM이 있으니 guard도 있다”고
간주하지 않는다.

### 1.2 용량 판단

- **3~4B BF16 한 개**: 격리된 시간대의 PoC는 가능성이 높다. BF16 가중치만 보면 약 6~8 GiB지만,
  비전 인코더, KV cache, CUDA graph, allocator, 요청 배치가 더해진다. Shieldstral 제작사는 BF16으로
  16 GB GPU 한 장에 들어간다고 명시한다
  ([Shieldstral 모델 카드](https://huggingface.co/mistralai/Shieldstral-1.0-3B)).
- **7~8B BF16**: 가중치 하한만 14~16 GiB이고 32k context의 KV cache까지 포함하면 기존 워크로드와
  공존 위험이 커진다. 양자화 없이 상시 배치할 첫 후보로 삼지 않는다.
- **11~12B BF16 VLM**: 가중치만 22~24 GiB 수준이므로 현재 `available` 31 GiB에 너무 가깝다.
  Llama Guard 4/3 Vision은 기능 비교 대상이지 이 호스트의 첫 배치 대상이 아니다.
- **두 개 동시 상주**: Qwen3Guard 4B와 Shieldstral을 동시에 띄우면 모델 자체보다 KV cache와 기존 엔진의
  변동 폭 때문에 안전 여유가 사라진다. 초기에는 한 번에 하나만 띄워 같은 트래픽 리플레이로 비교한다.

`nvidia-smi`가 전용 VRAM 여유를 제공하지 않는 플랫폼이므로 “31 GiB VRAM이 남았다”라고 표현하면 안 된다.
배포 판정은 아래를 같은 부하에서 계측한 뒤 내린다.

- 모델 로드 전후 `MemAvailable`, swap in/out, OOM 및 CUDA allocator 오류
- 텍스트와 이미지 각각 cold/warm p50·p95·p99, 동시성별 처리량
- 기존 Qwen3-VL의 TTFT와 tokens/s 변화
- 32k 최댓값뿐 아니라 실제 입력 길이 분포에서의 KV cache 사용량

## 2. 서빙 옵션 비교

네 옵션 모두 “모델이 해당 런타임에서 실제로 지원되는가”가 API 모양보다 우선한다. gardevoir는
런타임 고유 응답을 직접 알지 않고 하나의 내부 판정 계약만 보면 되므로, 교체 비용은 HTTP 어댑터가
흡수해야 한다.

| 런타임 | OpenAI 호환 | 멀티모달 | 장점 | 이 호스트에서의 위험 | 판정 |
| --- | --- | --- | --- | --- | --- |
| **vLLM** | `/v1/chat/completions`, logprobs 등. [공식 서버 문서](https://docs.vllm.ai/en/latest/serving/online_serving/) | 이미지 content part와 다중 이미지 지원. [공식 멀티모달 문서](https://docs.vllm.ai/en/latest/features/multimodal_inputs/) | continuous batching, 높은 처리량, Shieldstral 제작사 권장, 현재 GB10/ARM64에서 이미 두 엔진이 동작 | Shieldstral은 `vllm>=0.26.0`을 요구하지만 현재 컨테이너는 0.21.0. 새 조합의 ARM64 wheel/image와 회귀 검증 필요 | **1순위** |
| **SGLang** | chat/completions와 streaming 제공. [공식 OpenAI API 문서](https://docs.sglang.io/docs/basic_usage/openai_api_completions) | 별도 vision API 제공 | 높은 처리량, structured output, Qwen3Guard-Stream의 토큰 단위 예제가 있음 | Shieldstral 카드가 특정 수정 포함 버전을 요구한다. 이 GB10/ARM64에서 현장 검증이 없음 | 2순위·Qwen Stream 실험용 |
| **Ollama** | chat/completions, vision, tools, logprobs 지원. [공식 호환 문서](https://docs.ollama.com/api/openai-compatibility) | 파일/URL/bytes와 REST base64 이미지. [공식 vision 문서](https://docs.ollama.com/capabilities/vision) | 개발자 경험과 단일 모델 로컬 실행이 간단, GGUF/양자화에 유리 | 모델별 GGUF와 vision projector 패키징, 정확도 저하, GB10에서의 배치 처리량을 별도로 검증해야 함 | 개인 PoC 대안, 첫 운영 선택 아님 |
| **TGI** | OpenAI 호환 기능과 SSE/continuous batching 제공 | VLM 지원 문서가 있음. [공식 VLM 문서](https://huggingface.co/docs/text-generation-inference/basic_tutorials/visual_language_models) | 기존 운영 기능과 관측성이 성숙 | Hugging Face가 TGI를 maintenance mode로 전환하고 vLLM/SGLang 등을 권장한다. [공식 문서](https://huggingface.co/docs/text-generation-inference/en/index) | **신규 도입 제외** |

따라서 신규 모델 서버는 별도 포트의 **버전 고정 vLLM 컨테이너**가 기준이다. 기존 Qwen3-VL 컨테이너를
직접 업그레이드해 함께 싣는 방식은 생성 업스트림과 안전 판정의 장애 도메인·배포 주기·메모리 예산을
결합하므로 피한다. 이 결론은 현재 스택 변경을 승인한다는 뜻이 아니며, Phase 4 구현 전의 배치 방향이다.

## 3. 가드레일용 sLLM 후보

### 3.1 비교 기준

아래 VRAM 값은 별도 표기가 없으면 **BF16 가중치 2 bytes/parameter를 하한으로 삼은 서버 추정 범위**다.
context 길이, 동시성, 비전 인코더, KV cache와 런타임 예약에 따라 크게 늘어난다. 양자화는 메모리를
줄이지만 안전 분류 임계값과 recall을 바꿀 수 있어, 원본 BF16 기준선을 먼저 측정해야 한다.

`문서`는 네이티브 PDF 입력을 뜻한다. 조사한 가드 모델 중 PDF 바이너리를 직접 받고 좌표가 보존된
redaction을 반환하는 모델은 없다. 표의 “문서”는 추출 텍스트나 렌더링한 페이지 이미지로 검사할 수
있는지를 적었다.

| 모델 | 규모 | 모달리티 | 라이선스 | 안전·PII·인젝션 능력 | BF16 서빙 규모 | gardevoir 적합성 |
| --- | --- | --- | --- | --- | --- | --- |
| **[Shieldstral 1.0 3B](https://huggingface.co/mistralai/Shieldstral-1.0-3B)** | 3B 명칭, Hub 표시는 4B | 텍스트, 이미지, 텍스트+이미지; 문서는 전처리 | Apache-2.0 | 고정 taxonomy가 아니라 자연어 정책별 yes/no와 점수. 한국어 포함 12개 언어. PII·인젝션도 정책 질의로 물을 수 있으나 전용 성능은 별도 검증 필요 | 제작사 명시 16 GB 이내, 32k 학습 범위 | **멀티모달 1순위**. 노드 정책과 직접 맞고 한 토큰 판정·logprob 임계값 사용 가능 |
| **[Qwen3Guard-Gen-4B](https://huggingface.co/Qwen/Qwen3Guard-Gen-4B)** | 4B (0.6B·8B도 존재) | 텍스트; 문서는 추출 후 | Apache-2.0 | Safe/Controversial/Unsafe, 119개 언어·방언. 폭력, 불법행위, 성적 콘텐츠, PII, 자해, 비윤리, 정치, 저작권, 입력 jailbreak | 대략 10~16 GiB | **텍스트 기준선 1순위**. PII/jailbreak가 명시적이고 현재 vLLM 버전 범위와 맞음 |
| **[Qwen3Guard-Stream-4B](https://huggingface.co/Qwen/Qwen3Guard-Stream-4B)** | 4B | 텍스트 토큰 스트림 | Apache-2.0 | Gen 계열 taxonomy를 토큰별 분류. Qwen3 tokenizer token ID와 상태를 직접 받음 | 대략 10~16 GiB | OpenAI HTTP 판정기의 drop-in이 아님. 기존 holdback을 대체할 1차 선택으로 부적합 |
| **[Llama Guard 4 12B](https://huggingface.co/meta-llama/Llama-Guard-4-12B)** | 12B | 네이티브 텍스트+복수 이미지; 문서는 전처리 | Llama 4 Community, gated | MLCommons 14개 hazard, Privacy 포함. Code Interpreter Abuse는 text-only. 고정 taxonomy 중심 | 가중치만 약 24 GiB, 서버는 28 GiB 이상 예상 | 기능은 좋지만 현 호스트 여유·라이선스·gated access 때문에 첫 후보 아님 |
| **[Llama Guard 3 11B Vision](https://huggingface.co/meta-llama/Llama-Guard-3-11B-Vision)** | 11B | 텍스트+이미지 1장; image-only/text-only 용도 아님 | Llama 3.2 Community, gated | 14개 hazard와 Privacy. 영어 최적화, 프롬프트 분류 recall 0.623(자체 평가), adversarial 우회 가능 | 가중치만 약 22 GiB, 서버는 26 GiB 이상 예상 | 단일 이미지·영어·메모리 제약으로 탈락 |
| **[Llama Guard 3 1B/8B](https://huggingface.co/meta-llama/Llama-Guard-3-1B)** | 1B, 8B | 텍스트 | Llama 3.2/3.1 Community, gated | prompt/response 안전 분류. 지원 8개 언어에 한국어 없음. PII/Privacy taxonomy는 있으나 injection 전용 아님 | 1B 약 4~8 GiB, 8B 약 18~24 GiB | 1B는 초경량 기준선 가능, Qwen 대비 언어·라이선스 열세 |
| **[ShieldGemma 1](https://huggingface.co/google/shieldgemma-2b)** | 2B/9B/27B | 텍스트 | Gemma Terms, gated | 성적·위험·혐오·괴롭힘 4개 정책. PII·injection은 기본 범위 밖 | 2B 약 6~10 GiB부터 | 작지만 gardevoir가 원하는 PII/agent 보안 범위가 좁음 |
| **[ShieldGemma 2](https://huggingface.co/google/shieldgemma-2-4b-it)** | 4B | **이미지 전용 안전 분류** | Gemma Terms, gated | 성적, 위험, 폭력/gore 3개. yes/no 점수이며 PII 위치·얼굴·문서 인젝션은 다루지 않음 | 대략 10~16 GiB | 이미지 콘텐츠 필터로는 유효하나 Shieldstral보다 범위가 좁음 |
| **[Llama 3.1 Nemotron Safety Guard 8B v3](https://huggingface.co/nvidia/Llama-3.1-Nemotron-Safety-Guard-8B-v3)** | 8B | 텍스트; 문서는 추출 후 | NVIDIA Open Model License + Llama 3.1 조건 | 23개 taxonomy, PII/Privacy·Manipulation·Malware 포함, JSON 출력. 한국어는 학습 9개 언어에는 없고 zero-shot 확장 언어 | 대략 18~24 GiB | 정책/구조 출력은 좋지만 메모리·비전 부재로 2차 후보 |
| **[WildGuard](https://huggingface.co/allenai/wildguard)** | 7B | 텍스트 | Apache-2.0, 접근 조건 동의 | 유해 prompt, 유해 response, refusal 동시 판정. Privacy·오정보·악성 사용 등 13개. 영어 | 대략 18~22 GiB | 출력 의미는 유용하지만 한국어·메모리·비전에서 열세 |
| **[Aegis/Nemotron Defensive v1](https://huggingface.co/nvidia/Aegis-AI-Content-Safety-LlamaGuard-Defensive-1.0)** | Llama2 7B PEFT | 텍스트 | Llama 2 Community | PII/Privacy 포함 13개, prompt 분류 중심. 영어·구세대 기반 | 대략 18~22 GiB | 역사적 비교군. 최신 Nemotron/Qwen보다 우선할 이유가 없음 |

`Llama Guard 3 8B`의 별도 카드는
[여기](https://huggingface.co/meta-llama/Llama-Guard-3-8B)에 있다. 표에서 1B와 묶은 것은 같은 계열의
텍스트 대안이라는 의미이며, 라이선스 버전과 세부 taxonomy는 실제 채택 버전별로 다시 확인해야 한다.

### 3.2 벤치마크를 읽는 법

2026년 4월 ICLR workshop 논문
[Benchmarking Open-Source Safety Guard Models](https://arxiv.org/abs/2605.28830)은 14개 모델을
79,331개 텍스트 샘플과 8개 NIST safety 하위 범주에서 비교했다. 이 조건에서는 Qwen Guard 4B가
recall 83.97%, precision 68.79%, F1 75.63%로 가장 높은 recall을 보였다. Nemotron 8B는 recall
77.25%, WildGuard 7B는 73.83%였다. 반면 ShieldGemma 2B는 precision 82.20%지만 유해 입력의
54.51%를 놓쳤다. “큰 모델이 더 안전하다”거나 “precision이 높은 모델이 좋은 guard”라는 전제는
성립하지 않았다.

이 결과에는 세 가지 한계가 있다.

- 논문은 safety에만 집중해 cybercrime·privacy·정치 등 일부 보안/책임 범주를 데이터에서 제외했다.
  gardevoir의 PII와 agent action control 전체를 대표하지 않는다.
- Qwen의 `Controversial`을 `Unsafe`로 정규화했다. 이 선택은 recall을 높이고 오탐도 늘린다. 따라서
  gardevoir도 고위험 노드는 strict, 일반 콘텐츠 노드는 policy별 threshold로 분리해야 한다.
- Shieldstral은 2026년 8월 공개되어 이 비교에 포함되지 않았다. Shieldstral 카드가 보고한 VLGuard
  F1 97.7, UnsafeBench 81.8 등은 유망하지만 **제작사 평가**다. 한국어·문서·간접 인젝션을 포함한
  독립 검증이 아직 필요하다.

Shieldstral 자체도 언어/도메인별 편차, 잔여 label noise, 난독화·인코딩·매우 긴 문서에서의 신뢰도
저하를 제한사항으로 명시한다. 모델 카드 점수 때문에 규칙 티어나 taint·권한 검사를 제거하면 안 된다.

### 3.3 gardevoir verdict로의 매핑

모델은 `block/mask/allow`를 결정하는 정책 소유자가 아니다. guardrail 정의의 각 노드가 목표
`VerdictAction`을 소유하고, 모델은 그 노드의 자연어 조건이 충족됐는지만 판단해야 한다.

| 모델 출력 | 정규화 | gardevoir 적용 |
| --- | --- | --- |
| Shieldstral `yes` + score | 해당 정책 위반 | `pending_model` 노드가 선언한 `block` 또는 `mask` 후보 |
| Shieldstral `no` | 해당 정책 비위반 | 그 노드에 대해서 `allow` |
| Qwen `Unsafe` | 정책 위반 | 노드가 선언한 action 적용 |
| Qwen `Controversial` | 경계 사례 | 노드별 strictness에 따라 위반 또는 비위반. 고위험 ①/②의 기본값은 위반 쪽으로 검증 |
| Qwen `Safe` | 비위반 | 그 노드에 대해서 `allow` |
| timeout, 형식 오류, 서버 불가 | **판정 실패** | 조용히 `allow`로 바꾸지 않는다. checkpoint/위험별 fail mode를 명시하고 audit |

중요한 제약은 `mask`다. 텍스트에서 기존 규칙이 정확한 span을 이미 찾았다면 그 span을 마스킹할 수
있다. 모델만 “PII가 있다”고 답하고 위치를 주지 않았다면 전체 내용을 임의로 바꾸지 말고 block하거나
별도 localizer로 보낸다. 이미지도 동일하다. **정확한 span/box가 없으면 mask가 아니다.**

Shieldstral은 한 호출에 정책 질의 하나를 권장한다. 여러 policy를 넓은 한 문장으로 묶으면 전체
unsafe 여부는 얻을 수 있지만 어느 노드가 발화했는지, 따라서 어느 action을 적용할지 잃는다. 처음에는
`pending_model` 노드별 질의를 batch하고 vLLM이 연속 배치하도록 한다. 운영 데이터에서 동일 action과
threshold를 가진 질의를 안전하게 합칠 수 있음이 입증될 때만 호출 수를 줄인다.

## 4. 멀티모달 입력의 가능한 수준

### 4.1 가능한 것과 불가능한 것

| 입력/목표 | 가드 VLM만으로 | 필요한 보조 처리 | 권장 결과 |
| --- | --- | --- | --- |
| 폭력·노골적 성적 이미지·위험 행위 | 전체 이미지 의미 분류 가능 | 도메인별 threshold·한국어 caption 평가 | `block` 또는 격리 |
| 이미지와 질문을 합쳐야 드러나는 위해 | Shieldstral/Llama Guard 4가 결합 분류 가능 | 원래 text+image 순서와 역할 보존 | `block` |
| 이미지 속 주민번호·계좌·주소 텍스트 | “민감해 보임” 분류는 가능해도 위치 보장 없음 | OCR box → 규칙/checksum/NER → box redaction → 재검증 | 근거 box만 `mask`, 실패 시 `block` |
| 얼굴·차량번호판·QR/barcode | 일반 VLM의 존재 판단은 가능해도 완전한 검출·좌표 보장 없음 | 전용 detector/decoder와 좌표 | 정책에 따라 `mask` 또는 `block` |
| 스캔 PDF의 숨은 prompt injection | 일부 VLM/텍스트 guard가 잡을 수 있으나 우회 가능 | 페이지 렌더링 + OCR + 텍스트 규칙 + VLM, source taint 유지 | ②에서는 보수적 `block`/승인 |
| 네이티브 PDF redaction | 불가 | 파서, text layer와 좌표, 이미지/주석/첨부 파일 처리, 실제 PDF redaction | 검증 성공 시 `mask`, 아니면 `block` |
| 유해 개념만 지우고 나머지 이미지 보존 | 신뢰할 수 없음 | segmentation/inpainting은 별도 생성 시스템이며 누락·변조 위험 | 기본 `block`; 자동 “의미 마스킹” 금지 |

Microsoft Presidio도 이미지 PII redaction을 **OCR과 PII identification의 결합**으로 설명하며, 자동
탐지가 모든 민감 정보를 찾는다고 보장하지 않는다고 명시한다
([Presidio 문서](https://microsoft.github.io/presidio/)). 이는 특정 라이브러리를 채택하자는 뜻이 아니라,
분류와 위치 특정/redaction이 서로 다른 문제라는 구현 근거다.

### 4.2 이미지 파이프라인

이미지 입력은 다음 세 경로를 병렬로 평가하는 것이 안전하다.

1. **의미 경로**: 원본 이미지 + 동반 텍스트 + 정책 질의를 Shieldstral에 보내 전체 콘텐츠의
   유해성·간접 인젝션·민감 맥락을 분류한다.
2. **위치 경로**: OCR, 얼굴/번호판, barcode/QR detector가 span/box를 만든다. OCR 텍스트는 현재
   텍스트 규칙과 Qwen/Shieldstral 텍스트 판정에도 넣고, 정확한 box만 원본 픽셀에 redaction한다.
3. **검증 경로**: redaction된 결과를 다시 OCR/decoder에 통과시켜 대상 값이 남지 않았는지 확인한다.
   이미지 metadata(EXIF/XMP), 썸네일과 embedded preview도 제거하거나 검사해야 한다.

VLM의 bounding box 출력을 프롬프트로 유도할 수 있다는 사실은 안전한 redactor라는 증거가 아니다.
작은 글자, 회전·손글씨, 저대비, 가려진 문자, 여러 언어, 표 셀 관계, 얼굴 일부 노출에서 recall이
떨어질 수 있다. 특히 “한 번도 놓치면 안 되는” PII는 규칙/checksum, 조직별 사전, 전용 detector,
사람 검토를 조합해야 한다.

### 4.3 PDF·문서 파이프라인

PDF는 업로드 파일 하나가 아니라 text layer, raster image, vector drawing, annotation, form, attachment,
metadata의 묶음으로 취급해야 한다.

1. MIME/magic, 크기·페이지 수, 암호화 여부, 중첩 첨부와 파서 timeout을 먼저 검사한다.
2. text layer가 있으면 **문자와 페이지 좌표를 함께** 추출한다.
3. 모든 페이지를 이미지로 렌더링해, 스캔이거나 text layer가 불완전한 영역은 OCR한다. 예를 들어
   Docling도 스캔 PDF에는 OCR이 필요하고 full-page OCR이 더 느리다고 설명한다
   ([Docling OCR 문서](https://docling-project.github.io/docling/_generated/examples/full_page_ocr/)).
4. 추출 텍스트를 페이지·block·표 셀 경계와 함께 규칙 티어와 텍스트 guard에 보낸다. 페이지 이미지는
   멀티모달 guard에 별도로 보낸다.
5. PII span을 원본 좌표로 역매핑해 **실제 내용 스트림**을 redact한다. 검은 사각형 overlay만 얹으면
   아래 텍스트가 복사되므로 마스킹으로 인정하지 않는다.
6. 결과 PDF를 다시 파싱·OCR해 민감 값과 원본 metadata/attachment가 남지 않았는지 확인한다.

문서 전체를 32k context에 넣을 수 있다는 것은 문서 검사가 해결됐다는 뜻이 아니다. 페이지를 자르면
서로 다른 페이지에 나뉜 인젝션을 놓칠 수 있고, 전부 넣으면 지연·메모리와 long-context miss가
증가한다. 페이지별 판정에 문서 요약/이전 위험 상태를 더하는 계층적 방식이 필요하며, 최대 페이지·픽셀·
토큰 예산을 정책으로 제한해야 한다.

### 4.4 간접·멀티모달 prompt injection

OWASP는 외부 웹/파일의 간접 인젝션과 이미지에 숨은 지시의 멀티모달 인젝션을 별도 시나리오로
다루며, 완전한 예방책은 없다고 설명한다
([OWASP LLM01:2025](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)). 따라서 이미지 guard가
`safe`를 반환해도 다음 경계는 유지해야 한다.

- 외부 파일·웹·도구 결과는 신뢰 가능한 system/user 지시로 승격하지 않는다.
- source와 taint를 구조적으로 보존하고 최소 권한·tool schema·approval을 적용한다.
- ④ tool_call의 권한·인자 제약은 확률적 VLM이 아니라 결정적 규칙이 최종 소유한다.
- 난독화, split payload, Base64/QR, 보이지 않는 레이어, 다국어 혼합을 로컬 회귀 corpus에 포함한다.

## 5. gardevoir에 넣을 위치

### 5.1 현재 코드가 제공하는 연결점

현재 `Decision.HINT/MODEL_ONLY`은 규칙 실행 결과의 `pending_model`로 보존된다
([executor.py](../../backend/gateway/src/gateway/guardrail/plan/domain/executor.py)). `Inspector`는
여전히 `TIER_RULES`만 반환하고
([outcome.py](../../backend/gateway/src/gateway/guardrail/inspection/application/outcome.py)), proxy는 네
checkpoint의 `pending_model`을 audit에 합칠 뿐 모델을 호출하지 않는다
([proxy_service.py](../../backend/gateway/src/gateway/proxy/application/service/proxy_service.py)).

멀티모달 content의 현재 text extractor는 `type == "text"`인 part만 검사하고 이미지 URL의 숫자를
오탐하지 않도록 image part를 의도적으로 건너뛴다
([text.py](../../backend/gateway/src/gateway/guardrail/inspection/application/text.py)). 그러므로 모델 티어는
이 함수를 억지로 바꾸기보다, 원본 content part를 별도 멀티모달 입력으로 받아야 한다.

### 5.2 제안 경계

아래는 구현이 아니라 Phase 4의 배선 기준이다.

```text
compiled ExecutionPlan
  └─ rule Inspector ── conclusive ────────────────┐
                    └─ pending_model              │
                         └─ ModelJudge port       │
                              └─ HTTP adapter     │
                                   └─ normalized violation/score
                                                ──┴─ severity merge → audit
```

- **포트**: guardrail inspection application layer에 런타임 독립적인 `ModelJudge` 계약을 둔다. 입력은
  checkpoint, 정책 질의, 역할이 보존된 text/image parts, deadline이고 출력은 violation, score,
  provider category와 raw label의 최소 metadata다. OpenAI chat 응답 형식을 domain으로 들이지 않는다.
- **어댑터**: guardrail inspection infrastructure가 vLLM/SGLang/Ollama의 HTTP와 응답 parsing을 소유한다.
  어댑터가 자신의 HTTP client를 만들고 닫는다. malformed label도 정상 `allow`로 만들지 않는다.
- **lifetime**: 프로세스 수명의 adapter를 `app.py` lifespan에서 만들고 정리하며, per-request
  `Inspector`에는 `proxy/composition.py`가 주입한다. composition root는 HTTP driver를 직접 알 필요가 없다.
- **계획**: publish 시 `ExecutionPlan`에 pending 노드의 policy query, checkpoint, 선언 action,
  threshold/strictness와 model route를 컴파일한다. 요청 경로에서 DB를 읽거나 매번 정책 문장을 조립하지
  않는다. 이는 설계의 “요청 경로 DB 0회”와 맞는다
  ([설계 §4·§6](../superpowers/specs/2026-08-12-gardevoir-design.md)).
- **병합**: `safe/no`는 그 노드의 allow, `unsafe/yes`는 노드가 선언한 `VerdictAction`으로 바꾼 뒤 기존
  `block > mask > allow` 우선순위로 병합한다. dry-run은 같은 판정을 `would_have`에 기록한다.
- **감사**: `tier=model`, 모델 ID/revision, policy/node ID, score/threshold, latency, timeout/error,
  입력 모달리티와 최종 action을 기록한다. 원문 이미지·PII 자체를 audit에 복제하지 않는다.

### 5.3 checkpoint별 적용

| checkpoint | 모델 티어 적용 | 멀티모달 처리 | 원칙 |
| --- | --- | --- | --- |
| ① input | upstream 호출 전 | user의 원본 text/image/file을 검사 | unsafe면 비용을 쓰기 전에 block. PII는 근거 span/box가 있을 때만 mask |
| ② tool_result | 다음 LLM 입력 전 | 파일·웹·DB 결과의 text layer/OCR/page image | 간접 인젝션의 핵심 지점. source/taint를 유지하고 ①보다 보수적 threshold |
| ③ output | 사용자에게 내보내기 전 | 현재는 주로 텍스트; 향후 이미지 출력은 별도 post-process | non-stream은 전체 판정. stream은 holdback 안에서만 실시간 차단 가능 |
| ④ tool_call | 실행 전 | 이미지 의미보다 구조화 인자·권한이 핵심 | 모델은 보조 signal만 제공. 최종 action control은 결정적 규칙/승인 |

Qwen3Guard-Stream은 생성 모델과 같은 Qwen3 tokenizer의 token ID를 증분 전달할 때 가장 잘 맞고,
`trust_remote_code` 기반 custom architecture다. 다른 tokenizer면 매 토큰 재토큰화가 필요하다
([모델 카드](https://huggingface.co/Qwen/Qwen3Guard-Stream-4B)). 현재 gardevoir의 128자 holdback과
512자 sliding window에 외부 HTTP 분류를 매 토큰 호출하는 대체재가 아니다. 먼저 Gen/Shieldstral을
bounded window에 배치 호출하고, 실제 누출률과 지연을 측정한 뒤 Stream 전용 sidecar를 검토한다.

## 6. 권고 모델과 단계적 도입

### 6.1 추천 1 — Qwen3Guard-Gen-4B: 텍스트 기준선

선택 이유는 다음과 같다.

- Apache-2.0, 4B, 119개 언어·방언으로 한국어 PoC의 진입 장벽이 낮다.
- PII와 입력 jailbreak가 기본 taxonomy에 명시되어 있다.
- 같은 조건의 2026년 비교 연구에서 가장 높은 recall을 보였다.
- `vllm>=0.9.0` 또는 `sglang>=0.4.6.post1`의 OpenAI 호환 endpoint를 공식 지원한다. 현재 호스트의
  vLLM 0.21.0은 버전 숫자상 요구 범위를 만족하지만, 실제 모델/ARM64 조합은 아직 실행 검증하지 않았다.

향후 격리 PoC에서 사용할 공식 형태는 아래와 같다. **이번 조사에서는 실행하지 않았다.**

```bash
vllm serve Qwen/Qwen3Guard-Gen-4B \
  --port 8000 \
  --max-model-len 32768
```

초기 정책은 `Controversial`을 고위험 ①/②에서는 violation으로, 저위험 콘텐츠 정책에서는 audit-only로
비교해 precision/recall 곡선을 만든다. 출력 문자열 regex 하나에 의존하지 말고 허용 label/category를
엄격히 parsing하며 그 밖의 출력은 판정 실패로 처리한다.

### 6.2 추천 2 — Shieldstral-1.0-3B: 멀티모달 목표 모델

선택 이유는 다음과 같다.

- 단일 3B급 모델이 text-only, image-only, text+image와 한국어를 지원한다.
- 고정 taxonomy 대신 자연어 `Instruct/Query/Document`를 받아 gardevoir의 노드 정책을 재학습 없이
  반영한다.
- 출력이 단일 yes/no 토큰이고 logprobs로 연속 score를 만들 수 있어 threshold·audit에 적합하다.
- Apache-2.0이며 제작사가 BF16 16 GB 이내와 vLLM을 명시한다.

공식 예시는 `vllm>=0.26.0`과 다음 형태를 요구한다. **이번 조사에서는 실행하지 않았다.**

```bash
vllm serve mistralai/Shieldstral-1.0-3B \
  --port 8000 \
  --max-model-len 32768
```

현재 생성 업스트림의 vLLM 0.21.0을 올리는 것이 아니라, 별도 이미지/포트에 model revision과 runtime
digest를 고정해야 한다. `max_tokens=1`, `temperature=0`, `logprobs=true`로 yes/no 확률을 재정규화하는
공식 방식을 어댑터가 캡슐화한다. SGLang은 Shieldstral load fix가 포함된 버전을 요구하므로 첫 배치가
아니라 비교 실험으로 둔다.

### 6.3 단계

1. **오프라인 corpus 고정**: 한국어/영어의 safe·unsafe, 조직 PII, jailbreak, 간접 인젝션, tool_result,
   긴 문서, OCR 노이즈와 이미지-텍스트 결합 샘플을 만들고 false negative 비용을 먼저 정의한다.
2. **텍스트 model tier PoC**: Qwen3Guard-Gen-4B 한 개만 격리 서빙해 `pending_model` 노드와 verdict/audit
   mapping을 검증한다. 모델 서버 장애와 malformed output도 주입한다.
3. **Shieldstral A/B**: 같은 텍스트 corpus로 Qwen과 비교한 뒤 이미지 corpus를 추가한다. 두 모델은
   동시에 상주시키지 않고 같은 리플레이를 순차 실행한다.
4. **① input부터 제한 도입**: non-stream 입력의 HINT/MODEL_ONLY만 모델로 보낸다. p95와 오탐을
   확인한 뒤 ② tool_result를 켠다. ④ action control은 규칙/approval을 유지한다.
5. **문서 redaction은 별도 트랙**: OCR/좌표/redaction/재검증이 준비되기 전에는 PDF·스캔의 mask를
   약속하지 않고 block/quarantine만 제공한다.
6. **③ streaming은 마지막**: 설계의 holdback·sliding window 안에서 실제 leak rate와 추가 지연을
   측정한다. 한 토큰 분류 모델이라는 이유만으로 end-to-end 지연이 작다고 가정하지 않는다
   ([설계 §9](../superpowers/specs/2026-08-12-gardevoir-design.md)).

## 7. 라이브 확인 및 추가 검증 필요

웹 자료 자체는 2026-08-27에 확인했다. 아래 항목은 자료가 없어서가 아니라 **운영 환경과 gardevoir
정책으로 직접 실행해 봐야만 답할 수 있는 항목**이다.

- Shieldstral 요구 버전 `vllm>=0.26.0`의 GB10/aarch64 CUDA 이미지 가용성, build 없이 사용할 수 있는
  공식/검증된 이미지와 정확한 model revision
- Shieldstral과 Qwen3Guard 각각의 실제 통합 메모리 예약량, cold/warm p95·p99, 기존 Qwen3-VL TTFT에
  미치는 영향, 안정 동시성
- 한국어 PII·욕설·자해·위협·간접 인젝션에서의 recall/precision. 공개 영어 중심 점수를 한국어에
  전이하지 말 것
- Shieldstral의 자연어 PII/injection query 성능과 query 문구 민감도, 노드별 score threshold
- Qwen `Controversial`을 unsafe로 볼 정책별 기준과 오탐 비용
- 이미지의 작은 한글, 회전/손글씨, QR/Base64, screenshot, 여러 이미지, adversarial perturbation에서의
  false negative
- PDF parser/OCR/redactor 후보, 한글 OCR 품질, 좌표 역매핑, 표/양식/annotation/attachment/metadata,
  암호화 PDF의 fail mode
- 모델 서버 timeout/OOM/형식 오류 때 checkpoint별 fail-open/fail-closed/approval 정책. 기본 인자나
  조용한 allow로 숨기지 말 것
- 라이선스 법무 확인. Apache-2.0 후보도 모델/데이터의 제3자 권리 문구를 확인하고, Llama/Gemma/NVIDIA
  후보는 제품 배포 조건을 별도로 검토할 것
- Shieldstral은 아직 독립적인 대규모 비교 평가가 부족하다. 제작사 멀티모달 수치를 내부 corpus로
  재현한 뒤 기본 모델로 승격할 것

## 최종 선택표

| 역할 | 선택 | 배치 방식 | 채택 조건 |
| --- | --- | --- | --- |
| 텍스트 기준선 | Qwen3Guard-Gen-4B | 별도 vLLM, 한 번에 guard 모델 하나만 상주 | 한국어·PII·jailbreak recall과 기존 부하 공존 통과 |
| 멀티모달 목표 | Shieldstral-1.0-3B | 별도 vLLM 0.26+ 이미지/포트, revision 고정 | GB10/ARM64 호환, 독립 corpus, 16 GB급 예산과 p95 통과 |
| 이미지/PDF 정밀 mask | **sLLM이 아님** | OCR/좌표 detector/redactor/재검증 파이프라인 | 누락률, irreversible redaction, metadata/attachment 검증 통과 |
| 신규 서빙 런타임 | vLLM | model-tier 전용 장애 도메인 | 기존 업스트림과 독립 배포·관측·메모리 제한 |

따라서 Phase 4의 성공 기준은 “최신 가드 모델을 띄웠다”가 아니다. 규칙 티어가 모르는 노드만 의미
분류에 보내고, 모델 실패를 숨기지 않으며, 정확한 위치 근거가 있을 때만 mask하고, ①·②에서 agent의
권한 경계를 지키면서 설계의 지연 예산 안에 들어오는지가 성공 기준이다.
