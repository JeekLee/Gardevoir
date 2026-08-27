# Phase 4 — 모델 티어 스펙

- 작성일: 2026-08-27 (KST)
- 상태: 설계 확정. 구현은 4a(노드 모델 정렬) → 4b(모델 실행) 순.
- 근거 문서: 본 설계 문서 `2026-08-12-gardevoir-design.md` §4·§5·§6, 조사
  `docs/research/2026-08-27-sllm-guardrail-survey.md`와
  [`docs/research/2026-08-27-masking-localizer-survey.md`](../../research/2026-08-27-masking-localizer-survey.md).
- **파일 경로는 가드레일 BC 평탄화 이후 기준**(`definition/plan/inspection` → 다른 BC처럼 `guardrail/{domain,application,infrastructure,presentation}`). 4a 는 그 평탄화가 머지된 뒤 진행.

## 0. 이 문서의 위치

규칙 티어(§4·§6)는 구현·배포됐고, "모르겠음"을 `pending_model` 로 보존만 한다(모델 미호출). 이 문서는
**모델 티어를 붙이기 전에 노드 모델을 설계 문서 §5 로 되돌리는 정렬(4a)** 과 **그 위의 모델 실행(4b)** 을
규정한다. 성능상 load-bearing 인 컴파일된 선형 Program(§11.4, 0.62 ms)과 "요청 경로 DB·네트워크 0회"(§6)는
불변식으로 유지한다.

## 1. 문제 — 코드가 §5 에서 드리프트했다

설계 문서 §5 는 노드를 **네 역할**로 규정한다:

```
Extract   무엇을 볼지 (input / tool_result / output / tool_call)
Transform 입력을 다듬기 (lower / strip)
Check     조건을 확인하기 (regex / model / taint / side_effect / provenance)
Verdict   결론 (block / allow / ask / mask)
```

- **모델은 Check 의 한 종류**다 — regex·결정론 검사와 나란히.
- §4 는 티어(결론형/힌트형/모델형)를 "**체크가 선언하는 역할**"로 규정한다.

그러나 코드(`guardrail.py`)는:
1. `decision`(conclusive/hint/model_only)을 **VERDICT** 노드에 얹었다(문서상 Check 의 속성).
2. **모델 Check 노드 타입이 없다**(regex/transform/…/verdict 만 존재).

그래서 verdict 가 "검증·필터"처럼 느껴지고, 모델 정책을 verdict 필드로 얹으면 규칙 경로(regex→verdict)와
비대칭이 된다. 이 스펙은 §5 로 정렬한다.

## 2. 목표 노드 모델 (§5 정렬)

- **`NodeType.MODEL`** 추가 — Check 다(regex 의 동료). config: `{policy: str, checkpoint, strictness?}`.
  - `policy`: 자연어 정책 질의(모델에 물을 문장). 비어 있으면 저작 시점 검증 실패.
  - `strictness`(선택): 경계 사례 처리(예: Qwen `Controversial`, 아래 4b). 기본은 보수적.
  - Check 이므로 arity 는 **입력을 extract 에서 받는 형태**(regex 와 동일: `(1, 1)` — 무엇을 볼지 1개).
- **verdict 는 결론만** — config `{action: block/mask/allow, combine: any/all}`. `combine`의
  기본값은 `any`다. **`decision` 필드 제거.**
- **티어는 그래프 구조에서 나온다**(더 이상 필드 아님):

  | 티어 | 그래프 | 의미 |
  |---|---|---|
  | 결론형 | `extract → regex → verdict` | 규칙만으로 종료, 모델 미호출 |
  | 모델형 | `extract → model → verdict` | 규칙 없이 항상 모델 |
  | 힌트형 | `extract → regex, model → verdict(combine=all)` | regex 가 걸릴 때만 모델 호출(short-circuit), 모델이 확정 |

  힌트형의 "regex 걸릴 때만 모델"은 verdict `combine=all`의 short-circuit 에서 공짜로
  나온다(§3). `combine`을 생략한 verdict는 기존처럼 `any`(OR)다.

## 3. 실행 의미 — executor 3-상태 슬롯

현재 슬롯은 `None/bool/str`. 모델 Check 는 규칙 티어에서 평가 불가하므로 **PENDING 센티널**을 도입한다.

- **PENDING**: `True/False/None` 과 구분되는 단일 센티널 객체.
- **Model 명령**: 자기 out 슬롯을 `PENDING` 으로 둔다(규칙 티어에서 값을 못 냄).
- **Verdict `combine=any`**(3-상태 OR): 어떤 src가 확정 `True`면 발화(action 적용), 확정
  True 없이 하나라도 `PENDING`이면 `pending_model`에 node_id를 추가, 전부 `False`면 미발화.
- **Verdict `combine=all`**(3-상태 AND): 하나라도 확정 `False`면 미발화, False 없이 하나라도
  `PENDING`이면 `pending_model`에 node_id를 추가, 전부 확정 `True`면 발화(action 적용).
  - `verdict(all, False_regex, PENDING_model)` → 미발화 → **모델 미호출**(힌트형 short-circuit).
  - `verdict(all, True_regex, PENDING_model)` → pending → 모델 호출.

→ **런타임 산출물(`pending_model` = verdict node_id 들)은 지금과 동일 형태**다. 규칙-only 요청은 PENDING 이
전혀 안 생겨 기존 0.62 ms 경로 그대로. **4a 는 런타임 행동 보존**(모델 아직 미호출; pending 은 감사에만).

## 4. 컴파일 (§6 단계 ⑦ "모델 프롬프트 조립")

발행 컴파일에서 model-dependent verdict 마다 아래를 `ExecutionPlan` 에 싣는다(불변, 요청 경로 재조립 0회):

```
plan.model_nodes: dict[verdict_node_id, ModelNodeSpec]
ModelNodeSpec(node_id, checkpoint, policy, action: VerdictAction, strictness, model_route)
```

- `policy` 는 그 verdict 를 먹이는 **model Check 노드**에서, `action` 은 verdict 에서 온다(컴파일러가 결선).
- 초기 제약: **verdict 하나당 model Check 하나**(다중 model Check 는 이후). 저작 검증에서 강제.
- `model_route`: 어느 판정 모델/엔드포인트로 보낼지(초기엔 단일 Shieldstral 라우트).

## 5. 모델 실행 (async) — Phase 4b

규칙 Inspector 는 **동기 유지**(hot path). proxy 서비스(async)가 규칙 검사 **후** `pending_model` 이
비어있지 않을 때만 아래 단계를 돈다.

```
sync rule Inspector ── pending_model(verdict ids) ──▶ async ModelTier(proxy)
   plan.model_nodes[id] → JudgeRequest ─ ModelJudge 포트 ─ HttpxModelJudge 어댑터(Shieldstral)
      → JudgeResult(violated/score) ─ action 매핑 ─ block>mask>allow 병합 ─▶ audit(tier=model)
```

### 5.1 포트 (guardrail/application/port/model_judge.py)
```python
@dataclass(frozen=True, slots=True)
class JudgeRequest:
    checkpoint: str; node_id: str; policy: str; text: str
    parts: tuple[ContentPart, ...] = ()   # 멀티모달(이후)
    deadline_ms: int = ...

@dataclass(frozen=True, slots=True)
class JudgeResult:
    node_id: str; violated: bool | None    # None = 판정 실패(timeout/형식오류)
    score: float | None; raw_label: str

class ModelJudge(Protocol):
    async def judge(self, requests: Sequence[JudgeRequest]) -> Sequence[JudgeResult]: ...
```
도메인 어휘만. **배치 호출**(vLLM 연속배치). OpenAI 응답 형식은 도메인에 들이지 않는다.

### 5.2 어댑터 (guardrail/infrastructure/adapter/httpx_model_judge.py)
- 자기 `AsyncClient` 를 만들고 닫는다(§7 "어댑터가 전송을 소유").
- Shieldstral: `max_tokens=1, temperature=0, logprobs=true` → yes/no 확률을 재정규화해 `violated`+`score`.
- 모델 id/revision·엔드포인트는 설정. malformed/timeout → `violated=None`(조용한 allow 금지).

### 5.3 병합 / fail-mode
- `violated=True` → verdict 선언 action; `False` → 그 노드 allow; `None` → **체크포인트별 명시 fail-mode**.
- **MODEL Check가 기여하는 verdict는 `MASK`를 쓸 수 없다.** Shieldstral은 yes/no 판정만 내고
  위치를 주지 않으며, span을 내는 PII/GLiNER 모델은 같은 자연어 policy를 받지 못한다. 현재 스택에서
  자연어 policy 마스킹은 불가능하므로 `Guardrail.validate()`가 저작 시점에 거부하고 컴파일러도
  `ModelNodeSpec.action`에 싣지 않는다
  ([localizer 조사](../../research/2026-08-27-masking-localizer-survey.md)).
- regex Check가 찾은 span의 `MASK`는 유지한다. 최종 병합도 규칙 티어 결과를 포함해 기존
  `block > mask > allow`를 유지한다.
- model tier의 span 없는 `MASK`→`BLOCK` 승격은 오래된 계획을 위한 도달 불가 방어선이며, 도달하면
  경고를 남긴다.
- fail-mode 기본: 고위험 ①/② fail-closed(block 또는 승인), 저위험 설정형. 시계·기본값 우회 금지, 전부 감사.

### 5.4 lifespan / DI
- `app.py` lifespan 이 `HttpxModelJudge`(프로세스 수명, 자기 client) 생성·정리. 조립 루트는 httpx 를 import 하지 않는다(§7).
- `proxy/composition.py` 가 per-request 로 주입.
- **엔드포인트 미설정 시**: 모델 단계 비활성 + pending 노드는 명시 fail-mode 로 감사(조용한 allow 아님).

## 6. 체크포인트별 적용

| CP | 적용 | 원칙 |
|---|---|---|
| ① input | upstream 전, non-stream | 비용 쓰기 전 block. **1차 구현 범위.** |
| ② tool_result | 다음 upstream 전 | 간접 인젝션 핵심, ①보다 보수적 threshold |
| ③ output | non-stream 우선 | 스트리밍은 매 토큰 호출 아님 — 마지막(holdback, leak/지연 계측 후, §9) |
| ④ tool_call | **모델은 보조 signal만** | 최종 action 은 결정적 규칙/승인 소유, 모델이 규칙 block 못 뒤집음 |

멀티모달: `text.py` 는 이미지 part 를 의도적으로 건너뛰므로(§조사 §5.1), 모델 Check 의 멀티모달 입력은
원본 content part 를 보존하는 **별도 추출기**로 받는다(이후). 이미지/문서 정밀 mask 는 sLLM 아님 —
OCR/좌표/redaction/재검증 별도 트랙, 준비 전엔 block/격리만(조사 §4).

## 7. 감사 (tier=model)

`tier_reached=model`, 모델 id/revision, verdict/policy node id, score/threshold, latency, timeout/error,
입력 모달리티, 최종 action 을 기록. 원문 이미지·PII 는 감사에 복제하지 않는다(§10). 기존 감사 스키마의
`tier_reached` 를 그대로 쓴다.

## 8. 콘솔 에디터

- 신규 **Model Check 노드**: 정책 `policy` textarea(자연어) + strictness 선택. React Flow 팔레트에 Check 로.
- verdict 노드에서 `decision` 컨트롤 제거(결론=action 만).
- 노드를 §5 네 역할(**Extract / Transform / Check / Verdict**)로 팔레트에서 묶어 보여 저작자
  멘탈모델 정렬. transform은 Transform, regex·model·taint·side_effect·provenance는 Check다.
- verdict 인스펙터에서 입력 조합 `any`(하나라도 충족, OR) / `all`(모두 충족, AND)을 선택한다.
- 콘솔은 LAN 평문 HTTP(비보안 컨텍스트) — secure-context 전용 API 무가드 사용 금지.

## 9. 마이그레이션

기존 발행/초안의 verdict `decision` 을 구조로 옮긴다:
- `conclusive` → decision 제거(그대로 규칙→verdict).
- `hint`/`model_only` → 지금은 실제 모델을 안 불렀고 정책 텍스트도 없었으므로 **실 사용 사례가 없다**.
  존재 시 model Check 노드로 승격(빈 policy 는 발행 불가 → 저작자에게 노출). 마이그레이션 스크립트/일회 변환은
  실제 데이터 확인 후 최소로.

2026-08-27 로컬 Postgres 확인 결과 `default`의 draft와 발행본 v1~v4에 있는 verdict 25개는 모두
`conclusive`였고 `hint`/`model_only`는 0개였다. JSONB의 여분 `decision` 키는 레니언트 파서가 보존하되
검증과 컴파일에서 읽지 않아 무해하므로 Alembic 데이터 마이그레이션은 만들지 않는다.

노드 카탈로그 정렬 전 같은 DB를 다시 확인한 결과 `all`은 `default` draft와 v1~v4에 각 1개씩
총 5개, `length`는 v1에 1개 있었다. 따라서 이번에는 Alembic 데이터 마이그레이션이 필요하다.
각 `all`의 입력을 downstream verdict에 직접 연결하고 `combine=all`을 넣으며, `length(max_chars=N)`은
기존의 `len(text) > N`과 개행 의미를 보존하는 `regex("(?s).{N+1,}")`로 바꾼다. 콘솔
`templates.ts`의 AND 템플릿과 길이 템플릿도 같은 형태로 바꾼다.

같은 날 `default` 초안의 `in-model`이 `action=mask`인 `in-model-block`에 기여하는 조합도 확인했다.
새 제약을 도입하면 이 초안은 저장·발행할 수 없으므로 데이터 마이그레이션이 모든 저장 그래프를
상류 추적해 해당 verdict의 action을 안전한 방향인 `block`으로 올려 쓴다. 발행본과 초안을 함께
처리하며 손실 복원이 불가능해 downgrade는 거부한다. 미머지 migration은 공유 개발 DB에 적용하지
않는다.

## 10. 단계와 검증

- **4a(이번 워크트리)**: §5 노드 모델 정렬 — `NodeType.MODEL` Check, verdict `decision` 제거, executor
  3-상태(PENDING), 컴파일러(model_nodes + §6⑦), 콘솔 에디터, 마이그레이션. **런타임 행동 보존**(모델 미호출).
  검증: 규칙-only 경로 불변(0.62 ms 특성), 모델 Check 포함 그래프가 `pending_model` 로 감사됨, 서버 실기동.
- **4b(다음, 호스팅 이후)**: ModelJudge 포트/HttpxModelJudge 어댑터/async 병합/fail-mode/DI, **① input 텍스트 →
  실 Shieldstral**. 검증: 실 모델 판정, 모델 실패 주입, dry-run `would_have`, p95·오탐 계측.
- **이후**: ② tool_result → 멀티모달(별도 추출기 + 이미지) → ③ streaming.

운영 트랙(병렬): vLLM 0.26+ 통일(별도 컨테이너), Shieldstral 다운로드·검증, GB10 메모리 재할당(hosting 워크트리).

## 11. 비목표 / 열린 항목

- 4a 는 모델을 호출하지 않는다(행동 보존). 4b 가 실행을 더한다.
- 다중 model Check per verdict, strictness 세부(Controversial 매핑), 멀티모달 추출기, 문서 redaction 은 이후.
- ④ tool_call 의 최종 통제는 규칙/승인이 소유(모델 보조).
