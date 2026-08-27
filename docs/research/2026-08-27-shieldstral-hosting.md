# Shieldstral 호스팅 준비 실측

- 작업일: 2026-08-27 KST
- 대상: `spark-413c`의 라이브 `spark-inference` 스택, NVIDIA GB10/aarch64
- 범위: 메모리 실측, vLLM/GB10 이미지 조사, Shieldstral 사전 다운로드, 조건부 재할당 판단,
  후속 승인된 격리 canary와 Qwen 8B BF16 교체
- 결과: Shieldstral의 고정 digest text/image 실행을 검증했고, 사용자 승인 뒤 생성 업스트림을
  `Qwen3-VL-30B-A3B-Instruct`에서 `Qwen3-VL-8B-Instruct` BF16으로 한 번만 교체했다. Qwen의
  text/image/tool call와 기존 gateway 경로, Shieldstral 재기동 뒤 세 엔진 공존을 모두 검증했다.

## 결론

`mistralai/Shieldstral-1.0-3B`는 2026-08-27 현재 공개·비게이트 저장소였고, revision
`003ec7e2b0bab5f0e6307edbaf186fa5822b76f5`의 전체 파일을 표준 Hugging Face 캐시에
다운로드하고 두 가중치 파일의 SHA-256을 검증했다. 최초 조사 뒤 사용자가 canary를 별도 승인해,
공식 vLLM 0.27.1 ARM64 이미지의 고정 digest로 실제 모델 load·32k KV·text/image 한 토큰
logprobs까지 통과했다.

vLLM 0.26+의 공식 aarch64/CUDA 12.9 이미지는 소스 빌드 없이 이용할 수 있고, 선택한 0.27.1
digest는 GB10에서 Shieldstral을 실제 실행했다. 다만 GB10의 SM121을 공식 배포 산출물에
네이티브로 넣는 vLLM PR은 아직 병합되지 않았다. 이번 성공은 해당 digest의 PTX/JIT 경로를 포함한
**실행 검증**이지 SM121 네이티브 빌드 제공의 증거는 아니다.

30B Qwen과의 첫 공존은 기술적으로 성공했지만 NVIDIA 프로세스 합계가 89.0 GiB에 이르고 시스템
`MemAvailable`이 15~16 GiB까지 내려가 상시 운용 여유가 작았다. Qwen utilization만 줄이면 이미
작은 6.93 GiB KV cache가 먼저 사라지므로 초기에는 재시작하지 않았다. 이후 사용자가 답변 품질보다
가드레일 검증을 우선해 기존 Qwen을 유지하지 않아도 된다고 명시적으로 승인했다.

승인 뒤 [Qwen3-VL-8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)의 공개·비게이트
revision `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`을 먼저 완전히 다운로드하고, Shieldstral만
일시 중지한 다음 Qwen 하나를 BF16, utilization `0.25`, max len 32k로 교체했다. 제품명은 8B지만
모델 카드 표기는 9B이고, 실제 vLLM weight load는 16.65 GiB였다. 첫 교체에서는 gateway 무중단을
위해 `qwen3-vl-30b-a3b` 이름을 임시 보존했지만, 사용자가 이 표기가 실제 모델과 다르다고 지적한
뒤 compose project/service/container, served model, DNS와 gateway route를 모두
`qwen3-vl-8b-instruct`로 다시 전환했다. 이전 별칭은 현재 gateway에서 404다.

최종 공존 상태의 NVIDIA 프로세스 할당은 Qwen 28,583 MiB, Shieldstral 15,971 MiB, BGE 1,633
MiB이고 `MemAvailable`은 55 GiB였다. 세 엔진 health 200, Qwen text/image/tool call와 gateway
요청, Shieldstral 추론이 모두 성공했고 10초 `vmstat` 표본에서 swap-out은 0이었다. 따라서 이
호스트에서 **Shieldstral과 8B BF16 Qwen의 상시 공존은 현재의 가드레일 개발·기능 검증 용도로
가능하다고 판단한다.** 대표 동시성 부하의 p95/p99와 moderation 품질은 아직 검증하지 않았으므로
트래픽이 큰 production 승인과는 구분한다.

## A. 현재 할당과 사용량

### 측정 범위

13:55~14:05 KST에 `nvidia-smi`, `free -h`, `swapon --show`, `vmstat 1 5`, `df -h`,
`docker stats --no-stream`, 선택 필드만 추린 `docker inspect`, vLLM 시작 로그와 `/metrics`를
확인했다. 컨테이너 환경변수와 자격 증명은 출력하지 않았다.

GB10은 통합 메모리라 `nvidia-smi`의 `memory.total/used/free`가 `N/A`였다. 아래의 GPU 프로세스
메모리는 CUDA가 프로세스에 할당한 양이고 활성 요청의 working set과 같지 않다. 반대로
`docker stats`의 cgroup 메모리는 CUDA 할당 전체를 나타내지 않으므로 두 숫자 중 하나만으로 여유를
판단할 수 없다.

| 항목 | 13:55 KST | 다운로드·검증 후 14:04 KST | 해석 |
| --- | ---: | ---: | --- |
| 시스템 메모리 | 총 121 GiB, used 89 GiB, available 31 GiB | used 88 GiB, available 33 GiB | `available`은 회수 가능한 page cache를 포함한다. 전용 VRAM 여유가 아니다. |
| swap | 15 GiB 중 1.9 GiB 사용 | 3.6 GiB 사용 | 마지막 `vmstat`의 1초 표본 네 번은 `si=so=0`이었으나 이미 swap된 양이 있어 여유 예산으로 쓰지 않는다. |
| 루트 디스크 | 870 GiB 사용, 2.7 TiB 여유 | 885 GiB 사용, 2.7 TiB 여유 | 전체 HF snapshot 약 15 GB가 추가됐다. |
| GPU 순간 사용률 | 2% | 미재측정 | 순간 idle은 메모리·동시성 여유의 증거가 아니다. |

`nvidia-smi`의 프로세스별 할당은 다음과 같았다.

| 프로세스 | 할당 |
| --- | ---: |
| Qwen `VLLM::EngineCore` | 68,351 MiB = 66.75 GiB |
| BGE `VLLM::EngineCore` | 1,633 MiB = 1.59 GiB |
| 두 엔진 합계 | 69,984 MiB = 68.34 GiB |
| Xorg·GNOME·Firefox 등 그래픽 프로세스 | 약 2,235 MiB = 2.18 GiB |
| 위 NVIDIA 프로세스 전체 | 약 70.53 GiB |

`docker stats`의 cgroup 메모리는 Qwen 5.60 GiB, BGE 1.57~2.80 GiB, inference gateway
약 42~45 MiB였다. 세 컨테이너 모두 Docker memory limit이 `0`으로, 별도 상한이 없었다. Docker
healthcheck도 정의돼 있지 않아 실제 HTTP endpoint로 헬스를 확인했다.

### 실행 설정과 vLLM 메모리 프로파일

| 컨테이너 | 이미지·인자 | vLLM 시작 로그 | 현재 상태 |
| --- | --- | --- | --- |
| `spark-inference-qwen3-vl-30b-a3b` | `vllm/vllm-openai:v0.21.0-aarch64-cu129-ubuntu2404`, util `0.60`, max len `32768` | weights 58.17 GiB, KV 6.93 GiB/75,648 tokens, CUDA graph 0.64 GiB, 32k 최대 동시성 2.31배 | `/health` 200, `/v1/models` 200 |
| `spark-inference-bge-m3` | `vllm/vllm-openai:v0.19.1`, util `0.05`, max len `8192`, pooling runner | weights 1.06 GiB, CUDA graph 0.60 GiB | `/health` 200, `/v1/models` 200 |
| `spark-inference-gateway` | `spark-network-gateway:local`, host `0.0.0.0:10080` | Qwen/BGE를 컨테이너 DNS의 port 8000으로 라우팅 | running |

Qwen의 `0.60 × 121.7 GiB`는 약 73.0 GiB의 목표치지만, 실제 NVIDIA 프로세스 할당은 66.75
GiB였다. vLLM 시작 시 weights·activation·CUDA graph를 프로파일한 뒤 남은 부분만 KV cache로
만들기 때문에 utilization 숫자를 곧바로 “실사용량”이나 “회수 가능한 KV”로 읽으면 안 된다.
BGE도 `0.05 × 121.7 GiB = 6.09 GiB`를 전부 상주시킨 것이 아니라 NVIDIA 프로세스 할당은 1.59
GiB였다.

### 실제 요청 분포와 피크

현재 Qwen 프로세스가 2026-08-18에 재기동된 뒤 측정 probe 전까지 Prometheus에 완료 요청 69건이
남아 있었다.

- prompt 합계 6,460 tokens, 평균 93.6 tokens
- 69건 전부 1,000 tokens 이하, 64건은 500 tokens 이하
- 현재 구간 로그의 KV cache 피크 3.2%, running 1, waiting 0
- TTFT 합계/건수 기준 평균 0.168초, histogram상 67/69건이 0.5초 이하이고 전부 0.75초 이하

그러나 컨테이너가 2026-05-21 생성된 뒤 보존한 전체 로그에는 별도의 고부하 구간이 있다. 6월 23일에는
KV cache 99.9%, running 14, waiting 2~8이 같은 구간에 나타났고, 전체 로그의 개별 최대치는 running
23과 waiting 13이었다. 이 구간이 반복 가능한 운영 피크인지 일회성 부하시험인지는 로그만으로 구분할
수 없지만, 적어도 현재의 15분/9일 idle 표본만으로 KV를 과할당이라고 단정할 수 없게 한다.

읽기 endpoint 외에 작은 실제 요청으로도 현재 헬스를 확인했다.

| probe | 결과 |
| --- | --- |
| Qwen, `Reply with OK.`, `max_tokens=1` | HTTP 200, `OK`, curl start-transfer/총 0.146초 |
| BGE, `health check` embedding | HTTP 200, 1,024차원, 총 0.025초 |
| 최근 각 500 log lines의 OOM/CUDA/EngineDead/traceback 검색 | 일치 없음 |

### Shieldstral 16 GB급 예산

[Shieldstral 모델 카드](https://huggingface.co/mistralai/Shieldstral-1.0-3B/blob/003ec7e2b0bab5f0e6307edbaf186fa5822b76f5/README.md)는
BF16으로 16 GB 안에 들어간다고 명시한다. 현재 `MemAvailable` 31~33 GiB에서 16 GiB가 그대로
추가된다고 단순 계산하면 15~17 GiB가 남지만, 이는 다음을 포함하지 않은 낙관적 하한이다.

- 모델 로드·프로파일링 중의 임시 버퍼와 page cache
- Qwen의 활성 KV cache 증가와 두 엔진의 동시 CUDA 실행
- OS·ClickHouse·데스크톱의 변동과 이미 사용 중인 swap
- GB10에서 `gpu-memory-utilization`이 시작 단계의 완전한 hard cap이 아니라는
  [vLLM 이슈](https://github.com/vllm-project/vllm/issues/46307)

따라서 현재 상태를 “Shieldstral용 VRAM 31 GiB가 남음”이라고 표현하지 않는다. **통합 메모리
available 31~33 GiB와 NVIDIA 프로세스 할당 70.53 GiB가 함께 관측됐고, 16 GB급 추가 서버는
기동 가능성이 있지만 생성 피크와 공존할 안전 여유는 아직 입증되지 않았다**가 측정에 맞는 결론이다.

## B. vLLM/GB10 호스팅 조사

### 이미지 가용성

| 후보 | 확인 결과 | 판정 |
| --- | --- | --- |
| `vllm/vllm-openai:v0.26.0-aarch64-cu129-ubuntu2404` | linux/arm64, 12,720,698,282 bytes, digest `sha256:6a4570896a2f37fe052dc9f265f85a7581212c520da1324a721d0f222584e5bc` | Shieldstral 최소 버전의 공식 이미지. 소스 빌드 없이 pull 가능 |
| `vllm/vllm-openai:v0.27.1-aarch64-cu129-ubuntu2404` | linux/arm64, 12,261,377,842 bytes, digest `sha256:a20437a6f671c258abbe354858420c1b0ee93c12f5a64aa92473c0ea2a677cc0` | 1차 격리 canary 권고 후보. 최소 버전보다 새 patch이며 digest 고정 가능 |
| `nvcr.io/nvidia/vllm:26.07-py3` | NVIDIA signed/scanned GB10 안내 이미지지만 내부 vLLM은 0.24.0, CUDA 13.3.1 | Shieldstral의 `vllm>=0.26.0`을 만족하지 않아 제외 |
| `ghcr.io/timothystewart6/vllm-gb10:v0.26.0-gb10.6` | linux/arm64, SM121a 빌드, digest `sha256:fa87aea586e02719aba804f76e0895d1f096e8c387573e7981e2681589b3b712` | 재현 가능한 커뮤니티 fallback이지만 제3자 공급망과 CUDA 13.2/driver 조합 검증이 필요. 기본 선택 아님 |

앞의 두 upstream 이미지의 tag metadata와 platform digest는
[v0.26.0 Docker Hub API](https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags/v0.26.0-aarch64-cu129-ubuntu2404)와
[v0.27.1 Docker Hub API](https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags/v0.27.1-aarch64-cu129-ubuntu2404)를
조회하고 `docker manifest inspect --verbose`로 다시 확인했다.

공식 vLLM 0.26.0 release에는 CUDA 12.9 aarch64 wheel도 있다
([vLLM 0.26.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.26.0)). 하지만
SM121을 배포 wheel·Docker·FlashInfer AOT target에 추가하는
[PR #38484](https://github.com/vllm-project/vllm/pull/38484)는 2026-08-27 현재 open/unmerged다.
현재 호스트의 vLLM 0.19/0.21이 GB10에서 실제 동작하는 것은 유용한 현장 증거지만, 시작 로그도 GPU
capability 12.1에 대해 빌드가 지원하는 최대 capability가 12.0이라고 경고했다. PTX/JIT fallback으로
동작하는 것과 SM121 네이티브 산출물은 다르다.

NVIDIA의 [DGX Spark vLLM playbook](https://build.nvidia.com/spark/vllm/instructions)은 GB10 통합
메모리에서 pre-built container를 쓰는 경로와 낮은 utilization을 명시하지만, 현재 NGC 26.07
release note의 vLLM 버전은 0.24.0이다
([NVIDIA 26.07 release note](https://docs.nvidia.com/deeplearning/frameworks/vllm-release-notes/rel-26-07.html)).
따라서 이번 후보는 upstream 공식 0.27.1 ARM64/CUDA 12.9 이미지이고, 후속 canary에서
**Shieldstral load·한 토큰 logprobs·text/image 한 건을 모두 통과해 이 모델·호스트 조합의 검증
이미지로 승격했다**. 전날 공개된 0.28.0은 더 새롭지만 이 작업 시점에는 현장 정보가 더 적어 첫
canary 후보로 올리지 않았다.

공식 이미지가 모델 로드 중 SM121 kernel 문제로 실패할 때만 소스 빌드를 fallback으로 둔다.
[vLLM 공식 Docker 문서](https://docs.vllm.ai/en/v0.26.0/deployment/docker/#building-vllms-docker-image-from-source)는
`--platform linux/arm64` 빌드와 현재 GPU용 arch 제한을 지원하며, GH200 예시는 build RAM 약 15 GB,
약 25분, 결과 이미지 6.93 GB였다. GB10의 `12.1a` native build는 이보다 오래 걸릴 수 있고 vLLM,
PyTorch, FlashInfer/CUTLASS의 arch를 함께 맞춰야 하므로 난이도는 중간 이상이며 이번에는 수행하지
않았다.

### 배치안과 serve 명령

모델 카드의 최소 명령은 다음과 같다.

```bash
vllm serve mistralai/Shieldstral-1.0-3B \
  --max-model-len 32768
```

첫 canary 계획에서는 revision과 wire model name을 추가해 아래 형태로 고정했다. port `8001`과
host loopback 진단 port `10081`은 기동 전에 비어 있음을 확인했다. `0.14 × 121.7 GiB ≈ 17.0
GiB`는 모델 카드의 16 GB 설명을 바탕으로 한 **시작 후보이지 검증된 운영값이 아니다**.

```bash
vllm serve mistralai/Shieldstral-1.0-3B \
  --revision 003ec7e2b0bab5f0e6307edbaf186fa5822b76f5 \
  --served-model-name shieldstral-1.0-3b \
  --host 0.0.0.0 \
  --port 8001 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.14
```

- 컨테이너: `spark-inference-shieldstral-1.0-3b`, 기존 `spark-inference-net`에 별도 배치
- 이미지: 우선 `v0.27.1-aarch64-cu129-ubuntu2404`를 위 digest로 고정
- 진단: 필요하면 `127.0.0.1:10081 -> container:8001`만 bind. 외부에 직접 노출하지 않음
- gateway route: 모델 서버 검증 뒤 `http://shieldstral-1.0-3b:8001`을 별도 model route로 추가
- 첫 기동: `restart: no`로 crash loop를 막고 `MemAvailable`, swap in/out, Qwen TTFT, OOM/CUDA log를
  동시에 관측. 32k KV를 만들지 못하면 utilization을 자동으로 높이지 않고 중단
- 장애 도메인: Qwen 컨테이너와 이미지·port·lifecycle을 공유하지 않음

승인 뒤에는 이미 받은 revision의 HF cache root를 read-only로 마운트하고 네트워크 다운로드를 막은
아래 대응 설정을 적용했다. image tag가 아니라 확인한 digest로 실행했고 gateway route는 추가하지
않았다.

```text
image: vllm/vllm-openai@sha256:a20437a6f671c258abbe354858420c1b0ee93c12f5a64aa92473c0ea2a677cc0
model: /hf-model/snapshots/003ec7e2b0bab5f0e6307edbaf186fa5822b76f5
served-model-name: shieldstral-1.0-3b
port: 127.0.0.1:10081 -> 8001
network alias: shieldstral-1.0-3b
restart: no
max-model-len: 32768
gpu-memory-utilization: 0.14
```

### yes/no 판정

[고정 revision 모델 카드](https://huggingface.co/mistralai/Shieldstral-1.0-3B/blob/003ec7e2b0bab5f0e6307edbaf186fa5822b76f5/README.md#examples)의
공식 방식은 `/v1/chat/completions`에 다음 sampling을 보내는 것이다.

```json
{
  "max_tokens": 1,
  "temperature": 0.0,
  "logprobs": true,
  "top_logprobs": 20
}
```

첫 생성 위치의 token을 trim/lowercase한 뒤 `yes`, `yes.`, `"yes"`, `'yes'`와 대응하는 `no`
형태의 최대 logprob를 각각 `z_yes`, `z_no`로 잡고 다음처럼 두 후보 사이에서 재정규화한다.

```text
unsafe_score = exp(z_yes) / (exp(z_yes) + exp(z_no))
flagged = unsafe_score > 0.5
```

0.5는 공식 예시의 시작 threshold일 뿐 운영 정책값이 아니다. `yes`와 `no`가 top 20에 모두 없거나
응답 형식이 다르면 `allow`로 바꾸지 않고 판정 실패로 처리한다. `<Query>`는 하나의 yes/no 질문으로
쓰고 `<Instruct>/<Query>/<Document>`의 역할과 이미지 content part 순서를 보존한다.

### 메모리·지연·Qwen 영향 실측

초기 문서가 세운 가설과 승인 뒤 canary 실측은 다음과 같다. cold start는 container started부터 첫
`/health` 200까지를 쟀고, 지연은 curl start-transfer 기준이다.

| 항목 | 시작 추정 | canary 실측 |
| --- | --- | --- |
| 통합 메모리 예약 | 약 16~17 GiB 목표 | vLLM desired 17.04 GiB이나 NVIDIA 프로세스는 최종 19,195 MiB. `MemAvailable` 33→15~16 GiB, swap 3.6→9.3 GiB |
| cached cold start | 약 30~90초 | 187초. weights load 35.65초, engine init 95.83초와 FlashInfer autotune/CUDA graph capture 포함 |
| text 한 토큰 | warm 약 0.1~0.5초 | 첫 요청 0.164초, 이후 5회 평균 0.0438초(0.0431~0.0443초) |
| image+text 한 토큰 | warm 약 0.3~1.5초 | 첫 64×64 PNG 요청 0.184초 |
| 기존 Qwen TTFT | 동시 요청에서 악화 가능 | canary 전 5회 평균 0.1449초. 기동 직후 5회 평균 0.1705초/최대 0.2637초였으나 안정화 후 guard→Qwen 5쌍의 Qwen 평균은 0.1453초 |

짧은 분류가 `max_tokens=1`이라고 해서 prefill과 vision encoder가 공짜인 것은 아니다. 특히 guard를
모든 생성 요청의 앞뒤에 붙이면 두 엔진이 시간상 겹치므로, 단독 Shieldstral latency보다 Qwen TTFT의
회귀가 배포 승인 기준이다.

## C. 모델 사전 다운로드

2026-08-27 13:58~14:02 KST에 다음 명령으로 정확한 revision을 표준 캐시에 받았다.

```bash
hf download mistralai/Shieldstral-1.0-3B \
  --revision 003ec7e2b0bab5f0e6307edbaf186fa5822b76f5
```

Hugging Face API 관측은 `private=false`, `gated=false`, `disabled=false`였다. 토큰 없이 다운로드됐고
비인증 rate-limit 경고 외에 약관 동의나 인증 요구는 없었다.

- snapshot: `/home/jeek_lee/.cache/huggingface/hub/models--mistralai--Shieldstral-1.0-3B/snapshots/003ec7e2b0bab5f0e6307edbaf186fa5822b76f5`
- 파일: 12개, snapshot의 실제 크기 약 15 GB, `.incomplete` 0개
- manifest: `.gitattributes`, `README.md`, `chat_template.jinja`, `config.json`,
  `consolidated.safetensors`, `generation_config.json`, `model.safetensors`, `params.json`,
  `processor_config.json`, `tekken.json`, `tokenizer.json`, `tokenizer_config.json`
- `consolidated.safetensors`: 7,698,234,952 bytes,
  SHA-256 `25bcdaafaf81fe79982409ffaf9b3e269abe67d9064fed349b424944db92095e`
- `model.safetensors`: 7,698,241,104 bytes,
  SHA-256 `87753e30c8c321da478b83bbabebcd813cc9b3d0cee5c5b3d64349a8ee4172f7`
- tokenizer: `tekken.json` 16,275,088 bytes, `tokenizer.json` 17,077,322 bytes
- 두 weight SHA-256은 각 HF cache blob 이름과 정확히 일치했다.
- 전체 다운로드는 repo가 제공하는 두 safetensors 파일을 모두 보존하므로 runtime의 단일 weight
  footprint보다 디스크 사용량이 크다. 다운로드 뒤에도 루트 디스크 여유는 2.7 TiB였다.

## D. Qwen/BGE 초기 재할당 결정

**초기 단계에서는 적용하지 않았다.** `spark-inference` repository와 두 compose file은 clean
상태였고, 첫 측정과 Shieldstral canary 동안 어느 생성·embedding 컨테이너도 재시작하지 않았다.

Qwen의 현재 KV 6.93 GiB에서 utilization을 0.60→0.55로 내리면 단순 목표치 차이만 약 6.09 GiB다.
프로파일이 비슷하다고 가정하면 KV가 약 0.84 GiB만 남아 32k 한 건에 필요한 KV조차 만들지 못할
가능성이 높다. 0.57도 약 3.65 GiB를 회수하는 대신 현재 2.31배인 32k 동시성을 거의 1배로 줄인다.
게다가 보존 로그에는 KV 99.9%가 실제로 있었다. 이 상황에서는 몇 GiB 회수보다 생성 업스트림의
기동 실패·queue 증가 위험이 더 크다.

BGE는 NVIDIA 할당이 1.59 GiB이고 weights+graph 관측만 약 1.66 GiB라 더 낮출 근거가 없다. 따라서
Shieldstral 공존 여유는 Qwen/BGE를 임의로 줄여 만들지 않고, 승인된 canary에서 Shieldstral 자체의
실제 예약량과 Qwen 회귀를 먼저 측정했다. 장기적으로 Qwen utilization을 낮추려면 6월 피크가
재현 대상인지 확인하고, 실제 대표 동시성 replay에서 0.60과 후보값을 비교한 뒤 한 번에 Qwen 하나만
재시작해야 한다.

## E. 승인 후 격리 canary

### 기동과 메모리 프로파일

14:16 KST에 기준값을 다시 측정한 뒤 고정 digest를 pull했다. pull 뒤에도 Qwen/BGE health는 200,
`MemAvailable`은 33 GiB였다. 첫 container는 HF snapshot directory만 마운트해 내부 상대 symlink가
`blobs/`를 찾지 못했고, GPU load 전 14초 만에 exit 1로 끝났다. OOM은 아니었다. 이 실패 container는
`spark-inference-shieldstral-1.0-3b-attempt1`로 이름을 바꿔 로그와 함께 stopped 상태로 보존했다.

두 번째 container는 `models--mistralai--Shieldstral-1.0-3B` cache root 전체를 read-only로
마운트해 symlink 해석을 먼저 검증한 뒤 14:24:38 KST에 시작했다. 첫 health 200은 14:27:45였다.

- model architecture: `PixtralForConditionalGeneration`, BF16
- checkpoint: 7.17 GiB, weight load 35.65초, model loading 7.26 GiB/46.38초
- engine init: 95.83초, torch.compile 8.94초, CUDA graph 0.78 GiB/52초
- KV cache: 10.12 GiB, 102,016 tokens, 32,768-token request 최대 동시성 3.11배
- vLLM profile: desired 17.04 GiB, consumed weights+non-torch 6.12 GiB, peak activation 0.8 GiB,
  graph 0.78 GiB
- vLLM은 현재 KV 10.12 GiB 대신 `--kv-cache-memory=9868678063`의 9.19 GiB를 써야 요청한
  utilization 안에 맞는다고 로그에 남겼다. `.14`를 hard cap으로 취급하면 안 된다.
- NVIDIA process: Shieldstral 19,195 MiB, Qwen 68,351 MiB, BGE 1,633 MiB
- 시스템: `MemAvailable` 33→15~16 GiB, swap 3.6→9.3 GiB. load/graph 단계에서 수십 MiB/s의
  swap-out burst가 있었고, 준비 완료 뒤 30초 idle 창에서는 `so=0`으로 안정됐다.
- 같은 시점의 Docker cgroup 수치는 Shieldstral 3.75 GiB, Qwen 2.89 GiB, BGE 0.61 GiB로 CUDA
  프로세스 할당을 나타내지 않았다. root disk는 image pull 뒤 908 GiB 사용, 2.6 TiB 여유였다.

### 기능과 지연

공식 모델 카드의 system prompt, `<Instruct>/<Query>/<Document>`, `max_tokens=1`, temperature 0,
top 20 logprobs를 그대로 썼다.

| probe | 결과 |
| --- | --- |
| 폭력 위해 text | HTTP 200, `yes`, `z_yes=-0.002805`, `z_no=-5.877805`, unsafe score `0.997199`, 첫 요청 0.164초 |
| NVIDIA 64×64 PNG의 NSFW image+text | HTTP 200, `no`, `z_yes=-13.125002`, `z_no=-0.000002`, unsafe score `0.000001995`, 첫 요청 0.184초 |
| warm text 5회 | 평균 0.0438초, 범위 0.0431~0.0443초 |
| BGE embedding | HTTP 200, 1,024차원 |

image probe는 multimodal wire path의 동작 확인이지 실제 moderation 품질 평가가 아니다. production
threshold와 정책별 정확도는 별도 평가셋으로 정해야 한다.

Qwen의 동일한 `Reply with OK.`, 한 토큰 probe는 canary 전에 5회 평균 0.1449초
(0.1421~0.1531초)였다. canary 직후 첫 5회는 0.1427~0.2637초, 평균 0.1705초로 한 번의 큰
outlier가 있었다. 이후 Shieldstral→Qwen 순차 쌍 5회에서는 Shieldstral 평균 0.0438초, Qwen 평균
0.1453초(0.1431~0.1483초)로 outlier가 재현되지 않았다. 측정 내내 세 엔진 health는 200이고
running/waiting과 KV usage는 probe 종료 뒤 모두 0이었다.

### 당시 결정

**격리 canary의 기술 실행은 성공했지만 당시 30B Qwen과의 상시 공존 배포는 승인하지 않았다.** 단일
짧은 guard 요청의 정상상태 지연은 양호하고 SM121에서 text/image까지 실행됐지만, swap 점유가
5.7 GiB 증가했고 Qwen의 보존된 실제 피크와 대표 동시성 부하는 재현하지 않았다. gateway route를
추가하기 전 최소한 다음 조건이 필요하다.

1. explicit `--kv-cache-memory`로 `.14` overshoot를 제거한 별도 canary. 우선 vLLM이 계산한
   9,868,678,063 bytes를 사용하고, 더 낮출 때는 32k 동시성 요구를 먼저 정한다.
2. Qwen의 대표 prompt 길이·동시성과 Shieldstral text/image를 함께 replay해 Qwen TTFT p95/p99,
   queue, swap-out, OOM을 비교한다.
3. 승인 기준을 `MemAvailable`, 지속 swap-out, Qwen TTFT/queue 회귀로 수치화한다.

이 결정은 아래의 사용자 승인된 8B 교체 전 판단이다. Qwen utilization을 조금 줄이는 대신 모델
자체를 교체해 메모리 여유를 크게 만드는 후속 결과가 이를 대체한다.

## F. 승인 후 Qwen 8B BF16 교체 — 1차

### 다운로드와 고정 입력

Hugging Face API에서 `Qwen/Qwen3-VL-8B-Instruct`가 `private=false`, `gated=false`,
`disabled=false`이고 revision이 `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`임을 먼저 확인했다.
인증 없이 다음 명령으로 전용 local directory에 받았고 비인증 rate-limit 경고 외 오류는 없었다.

```bash
hf download Qwen/Qwen3-VL-8B-Instruct \
  --revision 0c351dd01ed87e9c1b53cbc748cba10e6187ff3b \
  --local-dir /home/jeek_lee/models/Qwen3-VL-8B-Instruct
```

- HF reported storage: 17,534,339,512 bytes
- safetensors shard: 4개, 각각 4,902,275,944 / 4,915,962,496 / 4,999,831,048 /
  2,716,270,024 bytes
- `.incomplete`: 0개, 컨테이너 read-only mount 확인
- architecture: `Qwen3VLForConditionalGeneration`, BF16, text 36 layers/hidden 4096
- 다운로드 뒤 root disk: 926 GiB 사용, 2.6 TiB 여유

기존 30B 서버에서 이미 동작하던 arm64 이미지
`vllm/vllm-openai@sha256:be0d527e5aea994435ca3d6526c421f5c8c8473943f13b75588505aa2117cb98`
(vLLM 0.21.0)을 그대로 사용했다. 새 이미지 도입과 모델 변경을 한 번에 섞지 않기 위한 선택이다.

### 한 번에 하나만 교체

14:46 KST에 Shieldstral만 정상 중지했다. Qwen/BGE health가 200임을 다시 확인한 뒤 Qwen compose의
해당 서비스 하나만 `--force-recreate --no-deps`로 재생성했다. gateway, BGE와 gardevoir 앱은
재시작하거나 변경하지 않았다. 30B 파일도 rollback을 위해 삭제하지 않았다.

1차 교체 직후의 임시 Qwen 설정은 다음과 같았다. 모델과 자원 설정은 맞았지만 wire 이름은 후속
전환 전까지 이전 30B 이름을 사용했다.

```text
model mount: /home/jeek_lee/models/Qwen3-VL-8B-Instruct -> /model (read-only)
served-model-name: qwen3-vl-30b-a3b  # 기존 gateway 호환 별칭
tensor-parallel-size: 1
dtype: bfloat16 (model config 자동 선택)
max-model-len: 32768
gpu-memory-utilization: 0.25
auto tool choice: enabled, parser: hermes
restart: unless-stopped
```

실제 compose 입력은
`/home/jeek_lee/work/personal/spark-inference/envs/inferences/qwen3-vl-30b-a3b/.env.local`에
있다. 기존 운영 방식대로 gitignored 파일이라 `spark-inference` repository는 clean 상태를
유지한다. 서비스·환경변수 이름에 남은 `30b-a3b`도 wire 호환용 이름이며 실제 mount와 `/v1/models`
root `/model`은 위 8B revision이다.

### 기동 프로파일과 기능 검증

container start 14:47:02부터 `/health` 200인 14:50:40까지 약 218초가 걸렸다. 가중치 4개 shard
load 87.39초, engine profile·compile·warmup 86.42초가 포함된다.

| 항목 | Qwen 8B BF16 실측 |
| --- | ---: |
| checkpoint / model load | 16.33 / 16.65 GiB |
| CUDA graph | 실제 pool 0.53 GiB, profile 추정 3.20 GiB |
| KV cache | 5.57 GiB, 40,512 tokens |
| 32,768-token 최대 동시성 | 1.24배 |
| NVIDIA 프로세스 할당 | 24,191 MiB |
| Qwen 단독 `MemAvailable` | 79 GiB |

| probe | 결과 |
| --- | --- |
| direct text | HTTP 200, `OK`; 첫 JIT 요청 20.55초 |
| 64×64 NVIDIA PNG | HTTP 200, `NVIDIA`; 0.346초 |
| Hermes tool call | HTTP 200, `get_weather({"city":"Seoul"})`; 1.694초 |
| 기존 gateway text route | HTTP 200, `OK`; 0.177초, gateway 재시작 없음 |

### Shieldstral 복귀와 1차 공존

Qwen 기능 검증 뒤 기존 `restart=no` Shieldstral container만 다시 시작했다. Shieldstral load 중에도
Qwen health는 계속 200이었고, 약 75초 뒤 둘 다 200이 됐다. 그 뒤 Shieldstral safe text는 `no`,
HTTP 200, 0.091초였다. Shieldstral→Qwen 순차 호출 3쌍은 모두 200이었다.

| 순차 쌍 | Shieldstral | Qwen |
| --- | ---: | ---: |
| 1 | 84 ms | 189 ms |
| 2 | 153 ms | 189 ms |
| 3 | 148 ms | 185 ms |

| 최종 항목 | 교체 전 30B+Shield | 교체 후 8B+Shield |
| --- | ---: | ---: |
| Qwen NVIDIA 할당 | 68,351 MiB | 24,191 MiB |
| Shieldstral NVIDIA 할당 | 19,195 MiB | 15,971 MiB |
| BGE NVIDIA 할당 | 1,633 MiB | 1,633 MiB |
| 세 엔진 합계 | 89,179 MiB | 41,795 MiB |
| 시스템 `MemAvailable` | 15~16 GiB | 59 GiB |
| swap 사용 | 9.3 GiB | 6.3 GiB |

최종 10초 `vmstat`의 매초 `so=0`이었고 세 엔진 모두 OOM 없이 health 200이었다. 남아 있는 6.3
GiB swap은 이전 메모리 압박 때 밀려난 page이며 새 공존 상태에서 증가하지 않았다. Qwen 8B의
32k 최대 동시성은 1.24배로 작으므로 장문 동시 생성 품질·처리량이 필요해지면 utilization을 즉시
올리기보다 대표 부하를 먼저 재현한다. 현재 우선순위인 가드레일 기능 검증에는 충분한 여유다.

위 값은 1차 교체 직후의 측정이다. 후속 이름 전환에서 동일한 model/utilization으로 Qwen을 다시
기동하자 CUDA 프로세스 할당은 28,583 MiB로 달라졌다. vLLM profile·graph allocation은 재기동마다
달라질 수 있으므로 현재 용량 판단에는 아래 최종값을 사용한다.

## G. canonical 8B 이름과 gateway 전환

### 영속 설정

`spark-inference`의 1:1 component 규칙에 맞춰 다음 새 구성을 만들었다. 기존 30B component는
rollback 입력으로 남겼지만 local manifest의 활성 대상에서는 제거했다.

```text
deployment/inferences/qwen3-vl-8b-instruct/
envs/inferences/qwen3-vl-8b-instruct/
envs/_manifest.local.env::INFERENCES=qwen3-vl-8b-instruct bge-m3 qwen3-reranker-0.6b
```

새 compose의 project, service, container는 모두 `qwen3-vl-8b-instruct`이고 vLLM
`--served-model-name`과 network DNS alias도 같다. 실제 host 입력은
`envs/inferences/qwen3-vl-8b-instruct/.env.local`이며 다음 값을 유지한다.

```text
model: Qwen3-VL-8B-Instruct@0c351dd01ed87e9c1b53cbc748cba10e6187ff3b
image: vllm/vllm-openai@sha256:be0d527e5aea994435ca3d6526c421f5c8c8473943f13b75588505aa2117cb98
gpu-memory-utilization: 0.25
max-model-len: 32768
tool parser: hermes
```

gateway fragment도 `model: qwen3-vl-8b-instruct`,
`url: http://qwen3-vl-8b-instruct:8000`으로 만들었다. `routes.rendered.yaml`을 손으로 편집하지 않고
local manifest와 fragment에서 `render.sh`로 생성했다.

active local manifest와 `.env.local`은 repository 정책대로 gitignored다. 새 component 정의와
`.env.example`은 commit `b9b14cd`로 `feat/qwen3-vl-8b-instruct` branch에 push한 뒤
[spark-inference PR #26](https://github.com/JeekLee/spark-inference/pull/26)으로 검토했고, required
check가 없는 clean/mergeable 상태를 확인해 merge commit `ed6d387`로 `main`에 반영했다.

### 순차 전환과 검증

15:01 KST에 1차 별칭 Qwen만 정상 중지했다. exit 0, OOM false를 확인하고 container와 로그를
`spark-inference-qwen3-vl-30b-a3b-alias-retired`로 보존한 뒤 새 canonical container를 시작했다.
Shieldstral과 BGE는 중지하거나 재시작하지 않았다. 새 Qwen은 15:01:38에 시작해 15:05:05에 health
200이 됐다.

| direct probe | 결과 |
| --- | --- |
| `/v1/models` | id `qwen3-vl-8b-instruct`, root `/model` |
| text | HTTP 200, response model `qwen3-vl-8b-instruct`, `OK`; 첫 JIT 20.51초 |
| image | HTTP 200, response model `qwen3-vl-8b-instruct`, `NVIDIA`; 0.343초 |
| tool call | HTTP 200, `get_weather({"city":"Seoul"})`; 1.763초 |

direct 검증 뒤 15:06 KST에 gateway 하나만 manifest 기반으로 재생성했다. gateway `/v1/models`에는
`qwen3-vl-8b-instruct`, `bge-m3`, `qwen3-reranker-0.6b`만 있고 이전 30B 별칭은 없다.

| gateway probe | 결과 |
| --- | --- |
| 새 8B text route | HTTP 200, `OK`, response model `qwen3-vl-8b-instruct`; 0.179초 |
| 새 8B image route | HTTP 200, `NVIDIA`; 0.253초 |
| 새 8B tool route | HTTP 200, `get_weather({"city":"Seoul"})`; 1.700초 |
| 이전 `qwen3-vl-30b-a3b` route | HTTP 404, not registered |
| BGE route 비회귀 | HTTP 200, 1,024차원; 0.742초 |

최종 NVIDIA 프로세스 할당은 Qwen 28,583 MiB, Shieldstral 15,971 MiB, BGE 1,633 MiB로 합계
46,187 MiB다. 시스템 `MemAvailable`은 55 GiB, swap 사용은 6.2 GiB였고 10초 `vmstat`의 매초
`so=0`이었다. Qwen, Shieldstral, BGE와 gateway는 모두 health 200이며 Qwen/gateway 최근 로그에
OOM, EngineDead, CUDA error, traceback이 없었다.

현재 `spark-inference-qwen3-vl-8b-instruct`, `spark-inference-shieldstral-1.0-3b`,
`spark-inference-bge-m3`, `spark-inference-gateway`는 모두 running이다. 사용자의 후속 지시를 위해
실행 container, retired container, 모델, 캐시와 세션을 정리하지 않았다.

## 수행하지 않은 변경

- BGE 설정 변경·재시작
- Shieldstral 설정 변경·재시작, gateway route 추가와 외부 노출
- gardevoir backend/frontend/infra 코드 변경
- HF cache, pulled image, 실패/실행 canary container, 작업 세션/워크트리 정리
