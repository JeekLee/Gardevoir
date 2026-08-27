# 콘솔 디자인·문구 감사

## 범위와 판정 기준

2026-08-27 Orca 내장 Chromium에서 배포 콘솔을 직접 조작했다. 관리자 로그인 뒤
로그인, 가드레일 목록, `default` 가드레일의 개요·입력 탭·노드 인스펙터·테스트
drawer, 감사 목록·상세, 프로바이더, API 키 화면을 확인했다. 실제 렌더 조건은
3113 × 1854 CSS px, dark color scheme, reduced motion 비활성이다. 배포 번들의 API 주소와
CORS 허용 오리진이 모두 `localhost`이므로 로그인 이후의 데이터 화면은 같은 배포본을
`http://localhost:3000`으로 열어 확인했다. `http://gardevoir-host:3000`에서 가드레일만
실패한 현상은 이 배포 설정 불일치 때문이며 이번 디자인 변경 범위에는 넣지 않는다.

판정 질문은 하나다. **이 요소나 문장을 지웠을 때 운영자가 정책을 저작하거나 판정을
추적하는 데 무엇을 잃는가?** 잃는 것이 없으면 삭제, 비가역성·보안·상태·원인처럼
행동을 바꾸는 정보가 사라지면 유지, 정보는 필요하지만 장황하면 수정한다.

심각도는 다음과 같다.

- S1: 주 정보보다 템플릿이나 설명이 먼저 보여 실제 작업 속도를 낮춘다.
- S2: 한 화면 안에서 중복되거나 장식이 정보처럼 보인다.
- S3: 국소적인 어조·상태·오류 문구 문제다.

## 전체 진단

현재 콘솔은 기능 경계와 접근성 구조는 명확하지만, 거의 모든 화면이 같은 문법을
복제한다. 작은 mono eyebrow → 매우 큰 Space Grotesk 제목 → 설명 부제 → 상태/메트릭
→ 라운드 카드가 반복된다. 가드레일·프로바이더·API 키 페이지의 `pageHeader`,
`headingBlock`, `eyebrow`, 5.8rem 제목 선언까지 사실상 동일하다
(`guardrails-page.module.css:6-45`, `providers-page.module.css:6-45`,
`api-keys-page.module.css:6-45`). 제품의 도메인 대신 생성 템플릿이 화면 정체성이 된
상태다.

팔레트도 전역의 옅은 녹색 radial gradient
(`src/_app/styles/globals.css:66-69`) 위에 녹색 점, 녹색 halo, 녹색 pill을 반복한다.
`--brand`가 선택·초점뿐 아니라 장식, 상태, 카드 레일, hover 그림자까지 맡아 의미가
희석된다. dark 실제 렌더에서는 넓은 빈 검정 면과 민트색 장식만 강하고, 운영 데이터는
작고 낮은 대비로 모인다.

라운드 카드 자체가 문제는 아니다. 폼·dialog·독립된 편집 영역의 경계에는 필요하다.
문제는 제목, 요약 수치, 필터, 목록 항목, 상세 section, 연결 안내가 전부 각각 카드가
되어 위계가 사라진다는 점이다. 그림자와 hover 상승까지 반복되어 클릭 가능한 것과
단순 정보가 같은 어포던스를 가진다.

## 화면별 발견

### 로그인 — S1, 삭제·축소

실제 렌더에서 폼보다 좌측 marketing hero가 화면 절반 이상을 차지했다. 사용자는 이미
로그인하러 왔고 다음 문구로 얻는 작업 정보가 없다.

- `src/_pages/login/ui/login-page.tsx:25-33`의 `"보호 체계 가동 중"`,
  `"모든 모델 경로를 안전하게 통제하세요."`,
  `"신뢰할 수 있는 업스트림을 연결하고 모든 요청을 정해진 경로로 전달하세요."`:
  삭제. 제품 소개이지 로그인 판단 정보가 아니다.
- 같은 파일 36-42의 `"게이트웨이 준비 완료"`, `"인증 대기 중"`: 삭제. 실제 health
  상태를 읽지 않는 가짜 상태 표시다.
- `src/features/authenticate/ui/login-form.tsx:73-75`의 `"콘솔 접근"`과
  `"관리자 계정으로 모델 경로와 가드레일을 관리하세요."`: 삭제. `관리자 로그인`과
  이메일·비밀번호 라벨이 이미 말한다.
- 로그인 버튼의 장식 화살표(116-118): 삭제. 동작은 `로그인`뿐이다.
- `"콘솔 계정은 애플리케이션 gdv_ 키와 별도로 관리됩니다."`(49-50): 유지. 사람이
  애플리케이션 키를 붙여 넣는 실수를 막는 보안 경계다.
- 세션 만료와 권한 부족 오류: 유지하되 원인과 다음 행동만 남긴다.

레이아웃은 hero + 카드에서 브랜드·폼 한 열로 바꾼다. 폼 그룹의 얕은 경계는 유지하되
`login-page.module.css:150-156`의 1.4rem radius와 큰 shadow를 제거한다.

### 가드레일 목록 — S1, 주 정보 전진

실제 렌더에서 대형 제목·두 문장 부제·검사 순서 레인·로그인 사용자 행을 지난 뒤에야
가드레일 두 개가 보였다. 운영자가 보러 온 것은 이름, 초안/발행 버전, 검사 지점,
판정 결과다.

- `src/_pages/guardrails/ui/guardrails-page.tsx:84-89`의 `"정책 통제 영역"`과
  `"입력부터 … 설계하세요. 게이트웨이가 … 발행합니다."`: 삭제. 목록과 상세 편집기가
  기능을 직접 보여준다.
- 검사 순서 ①②④③과 `"번호는 검사 지점 ID이며, 레인은 실제 요청 실행 순서입니다."`
  (101-112): 유지·압축. 번호와 실행 순서가 일치하지 않아 실제 오해를 막는다.
- `"로그인 사용자 root"`(121-123): 삭제. 전역 header에 사용자와 역할이 이미 있다.
- 카드의 `01/02` index와 `"정책 그래프"`(221-227): 삭제. 정렬 의미가 없는 장식과
  자원 유형 반복이다.
- `초안`, `발행 vN`, `미발행`, 검사 지점, 결과, 검사/판정 수: 유지. 배포 상태와 정책
  범위를 한눈에 비교하게 하는 핵심 데이터다. 다만 pill/원형 장식을 평문 상태로 낮춘다.
- 빈 화면의 `"에이전트가 읽고 실행할 범위를 통제하세요"`(364): `가드레일 없음`으로
  수정. 첫 동작은 `새 가드레일` 하나면 충분하다.

`guardrails-page.module.css:252-282`의 큰 radius, shadow, 녹색 gradient 레일, hover 상승을
삭제하고 촘촘한 목록 surface로 만든다. 이름·상태·검사 지점·판정을 가장 강하게 둔다.

### 가드레일 상세 개요 — S1, 검사 지점 우선

현재 개요는 `overviewHero` 안에 설명과 4개 메트릭 카드, 다음에 다시 4개 검사 지점
카드, 마지막에 앱 연결 카드를 둔다. 전형적인 hero + metrics 템플릿이며 정책의 실제
구성은 두 번째로 밀린다.

- 검사 지점 구성 4개를 개요 첫 정보로 이동한다. 이것이 가드레일의 내용이다.
- `src/features/guardrail-editor/ui/guardrail-overview.tsx:86`의 `"가드레일 개요"`와
  233-237의 `"검사 지점 구성"`, `"번호는 …"`, `"카드를 선택해 …"`: 삭제. 현재
  page/tab/버튼 구조가 이미 말한다.
- 설명 textarea와 검사 지점·노드·판정·결과 수치는 유지. 정책 비교와 발행 전 검토에
  쓰인다. `guardrail-editor.module.css:469-500`의 각 수치별 라운드 카드는 제거하고 한
  줄 summary로 낮춘다.
- `"그래프와 함께 저장됩니다"`(114)와 dirty 상태 설명 `"설명과 그래프 변경은 …"`
  (69-72): 삭제. 저장 버튼과 dirty 상태명이 이미 말한다. 글자 수만 남긴다.
- 각 검사 지점의 `"사용자 의도를 검사합니다"` 등
  (`features/guardrail-editor/model/catalog.ts:20-38`): 삭제. `입력/사용자 메시지`,
  `툴 결과/신뢰하지 않는 데이터`와 의미가 겹친다.
- 앱 연결 curl, 모드, header 의미: 유지. 통합 계약(§7)을 실제로 사용하는 정보다.
  다만 `"OPENAI 호환 연결"`과 `"…실제 앱 연결 형식을 확인하세요"`는 삭제한다.

`overviewHero`의 radial gradient와 중첩 카드
(`guardrail-editor.module.css:309-325`, 476-484)를 제거한다. 상태는 이미 상세 header에
있으므로 개요의 두 번째 pill은 없앤다.

### 가드레일 탭·캔버스·인스펙터 — S1, 편집 대상 우선

입력 탭 실제 렌더에는 탭 순서 설명, 초안 로드 설명, 배치 보존 설명, 검사 지점 설명,
카탈로그 그룹 설명이 캔버스 전에 연속으로 나타났다. 캔버스와 inspector가 작업 대상인데
설명이 상단을 점유한다.

- `editor-tabs.tsx:77-79`의 탭 순서 설명: 삭제. 목록 화면에 한 번 남기고 탭 라벨의
  번호로 충분하다.
- `guardrail-editor.tsx:168`의 `"초안을 불러왔습니다. 저장하기 전 변경 내용은 …"`:
  삭제. 아무 행동도 요구하지 않는 성공 서술이다. 복구·읽기 전용·저장·발행 결과처럼
  상태가 바뀐 경우의 live announcement는 유지한다.
- 같은 파일 727-729의 두 문장은 `"노드 배치는 저장되지 않습니다."`로 수정한다.
  현재 계약의 실제 제약이므로 삭제하면 안 된다.
- `editor-tabs.tsx:65`의 집 모양 `⌂`: 삭제. `개요` 텍스트와 중복된다.
- 카탈로그 그룹의 `"무엇을 볼지"`, `"어떻게 볼지"`, `"어떤 결론을 낼지"`
  (`catalog.ts:61-63`)와 inspector의 일반 node description(예:
  `"이 검사 지점의 텍스트를 읽습니다."`): 삭제. node 이름과 category를 반복한다.
  RE2 문법, 기본값, 위험 동작처럼 설정 결정을 바꾸는 필드 도움말은 유지한다.
- inspector의 read-only 검사 지점 아래 `"검사 지점은 현재 탭에 고정됩니다."`
  (`node-inspector.tsx:410-419`): 삭제. read-only 값과 탭이 이미 제약을 보여준다.
- 캔버스 node, 선택/오류/테스트 강조와 키보드 node roster: 유지. 모두 편집·검증·접근성
  기능이다. 단순 surface의 radius와 shadow만 낮춘다.

### 가드레일 테스트 drawer — S2, 모드만 명확히

- `guardrail-test-panel.tsx:197-201`의 제목 아래
  `"저장된 초안을 즉석에서 컴파일하고 … 실시간으로 확인합니다."`: 삭제. `업스트림
  테스트`와 결과 영역이 말한다.
- `"초안 강제 적용 테스트"` + `"저장된 초안을 강제 적용 모드로 검사하며 발행본에는
  영향을 주지 않습니다."`(214-218): `저장된 초안 · enforce · 발행본 영향 없음` 한
  줄로 수정. 실행 semantics는 반드시 남긴다.
- 모델 라벨 아래 `"등록된 프로바이더 모델"`(237-241): 삭제. `업스트림 모델`과 select
  option이 이미 말한다. 로딩 중 상태만 live text로 유지한다.
- `"실제 호출 테스트"`: `테스트`로 수정. dirty일 때는 `저장 후 테스트`로 동작 순서를
  보존한다.
- drawer 등장 자체는 상태 전환을 설명하는 짧은 motion이므로 유지할 수 있으나, 내부
  카드·pill 장식은 제거한다. reduced-motion 분기는 그대로 보존한다.

### 감사 목록 — S1, 표가 화면의 주인

실제 렌더에서 hero, 일곱 개 summary 카드, 큰 필터 카드 뒤에야 이벤트 표가 시작했다.
감사 화면의 1차 질문은 “최근 무엇이 차단/마스킹됐는가”이고 표의 행이 답이다.

- `src/_pages/audit/ui/audit-page.tsx:118-127`의 `"감사 · 관측"`,
  `"요청이 어떻게 판정됐는지 확인하세요"`, 설명 부제,
  `"ClickHouse 실시간 조회"`: 제목 `감사`만 남긴다. 저장소 이름과 가짜 live 점은
  운영 판단 정보가 아니다.
- summary의 전체/액션별 수/지연 p50·p95(203-276): 유지. 현재 필터 범위의 운영
  신호다. 개별 메트릭 카드를 없애고 작은 한 줄 요약으로 만든다.
- 필터의 `"필터"` eyebrow + `"범위 좁히기"`(331-346): `필터` 한 제목으로 수정.
  여덟 필드와 적용/초기화는 유지한다.
- 이벤트 section의 `"이벤트"` eyebrow(147): 삭제. `감사 기록`과 `N건 표시`가 충분하다.
- 표의 action badge는 유지한다. 차단·마스킹을 빠르게 스캔하게 하는 의미 있는 상태
  인코딩이다. 단, 과한 pill radius를 낮춘다.
- `"마지막 기록입니다."`: 삭제. 더 보기 버튼이 없다는 상태로 충분하다.

### 감사 상세 — S2, 중첩 카드 제거

실제 dialog에는 `이벤트 상세` → `판정 근거 드릴다운` → `요청 식별자와 검사 결과를 …`
세 겹 제목이 있고, 요청과 결과·걸린 검사·판정 근거가 다시 같은 라운드 카드가 된다.

- `audit-page.tsx:574-578`을 제목 `감사 이벤트` 하나로 줄인다.
- `"원본 판정 필드"`(639): 삭제. `판정 근거`와 실제 key/value가 충분하다.
- 감사 ID, 요청 ID, 키 ID, 가드레일 버전, 모드, 지연, 토큰, 원본 verdict는 모두 유지.
  재현과 상관관계 분석의 핵심이다.
- `audit-page.module.css:619-625`의 section별 배경·border·radius를 제거하고 divider로
  구분한다. dialog 자체 경계와 focus 복원·닫기 accessible name은 유지한다.

### 프로바이더 — S1, 엔드포인트·모델 우선

- `providers-page.tsx:88-92`의 `"업스트림 라우팅"`과 설명 부제: 삭제.
- 각 카드의 순번, 양쪽 gradient gate 레일, 중앙 점
  (`providers-page.module.css:192-259`): 삭제. 엔드포인트 연결 상태처럼 보이지만 실제
  health를 나타내지 않는 장식이다.
- 카드의 `"프로바이더"` 반복 label은 삭제. 이름이 자원 정체성이다.
- `API 키 연결됨/없음`, base URL, 모델 목록, 수정 시각: 유지. 라우팅과 credential
  상태를 판단하는 실제 데이터다. API 키 상태는 pill 대신 짧은 텍스트로 보인다.
- 빈 화면은 `프로바이더 없음` + `프로바이더 추가`만 남긴다.

### API 키 — S1, 키 목록 우선

실제 렌더에서는 긴 앱 연결 카드가 23개 키 표보다 먼저 온다. 이미 키를 운영하는
관리자에게 목록이 주 정보다.

- `api-keys-page.tsx:100-105`의 `"앱 크레덴셜"`과 설명 부제: 삭제.
- 발급 키 표를 앱 연결 안내보다 먼저 배치한다. 키 이름, preview, 생성/만료, 상태,
  수정/폐기는 모두 유지한다.
- `"로그인 사용자 root"`: 삭제. 전역 header와 중복된다.
- 앱 연결 panel의 curl, 가드레일, 모드, API 키 placeholder와 header 의미는 유지한다.
  `app-connection-panel.tsx:20-22, 66-68`의 `"앱 연결 방법"`, `"OpenAI 호환 연결"`,
  설명 부제는 `앱 연결` 한 제목으로 줄인다.
- Authorization·Guardrail·Mode 설명(147-159)은 Gardevoir 통합 계약의 비자명한 부분이라
  유지하되 카드 세 개처럼 보이지 않게 압축한다.
- active/revoked/expired는 의미 있는 상태이므로 유지한다. 장식 pill만 낮춘다.
- 평문 키가 한 번만 보인다는 생성 dialog 문구는 보안상 유지한다.

## 오류·상태 문구

`src/shared/api/error-message.ts`는 `"잠시 후 다시 시도하세요"`, `"연결 상태를 확인한 뒤
다시 시도하세요"`, `"입력 내용을 확인한 뒤 다시 시도하세요"`를 네트워크·timeout·응답
형식·500·validation에 관계없이 반복한다(5-15, 43, 52-57, 67-76). 실제 화면에는 이미
`다시 시도` 버튼이 있고, 기다리면 해결되는지 근거도 없다.

다음 규칙으로 수정한다.

- 알려진 원인 + 구체 행동이 있으면 둘 다: `세션이 만료되었습니다. 다시 로그인하세요.`
- 원인은 알지만 사용자가 바꿀 수 없으면 원인만: `게이트웨이 응답 시간이 초과되었습니다.`
- 필드·node·설정 위치가 있으면 그 위치만 지목: `선택한 노드의 필드를 확인하세요.`
- 목록 refetch 버튼이 있으면 본문에서 다시 시도를 반복하지 않는다.
- request ID/reference는 유지한다. 운영자가 서버 로그와 연결하는 실제 도구다.
- toast/live region은 동작 이름으로 끝낸다: `저장됨`, `발행됨`, `삭제됨`, `복사됨`.
  `~할 수 있습니다`, `~했습니다` 같은 축하·서술을 덧붙이지 않는다.

## 개선 원칙

### 디자인

1. 기존 light/dark token은 유지하되 ambient gradient를 제거한다. brand color는 primary
   action, focus, selected, 위험/판정 상태에만 쓴다. 장식 점·halo·gradient rail에는 쓰지
   않는다.
2. page title은 자원 이름 크기로 줄이고, mono uppercase eyebrow는 삭제한다. mono는 ID,
   코드, 수치에만 쓴다.
3. 화면마다 주 정보를 먼저 둔다. 감사=이벤트 표, 가드레일 상세=검사 지점/캔버스,
   프로바이더=엔드포인트+모델, API 키=키 표다. 설명·연결 예시는 뒤로 보낸다.
4. 한 작업 그룹에 surface 하나만 쓴다. 그 안의 metric·section·field마다 다시 라운드
   카드를 만들지 않는다. shadow는 modal/drawer처럼 겹침을 표현할 때만 쓴다.
5. hover 상승과 장식 animation은 제거한다. spinner·drawer 전환처럼 상태 변화를 설명하는
   motion만 유지하고 `prefers-reduced-motion` 분기를 보존한다.
6. 아이콘은 기능이나 상태를 더 설명할 때만 쓴다. `＋`, `→`, `⌂`, 순번, live dot처럼
   텍스트를 반복하거나 실제 상태를 측정하지 않는 장식은 삭제한다.

### 문구

1. 제목은 자원 또는 동작 이름: `감사`, `필터`, `업스트림 테스트`, `발행`.
2. 문장은 비가역성, 보안, persistence, 실행 mode처럼 행동을 바꿀 때만 남긴다.
3. 라벨·값·control이 이미 표현한 내용을 help text로 반복하지 않는다.
4. 상태 결과는 `저장됨`, `발행됨`, `복사됨`; 진행은 `저장 중…`; 오류는 원인 + 가능한
   행동만 쓴다.
5. 접근성 이름, label, aria-live, role=status/alert, focus 관리 문구는 장식 문구와 별개로
   취급한다. 화면에서 문장을 지워도 필수 accessible name과 상태 announcement는 보존한다.

## 2단계 삭제·수정 대상 목록

| 파일 | 현재 문자열/스타일 | 판정 |
|---|---|---|
| `src/_pages/login/ui/login-page.tsx` | `보호 체계 가동 중`, `모든 모델 경로를 안전하게 통제하세요.`, hero 부제 | 삭제 |
| 같은 파일 | `게이트웨이 준비 완료`, `인증 대기 중`과 signal 장식 | 삭제 |
| `src/features/authenticate/ui/login-form.tsx` | `콘솔 접근`, 관리자 로그인 부제, 버튼 `→` | 삭제 |
| `src/_app/styles/globals.css` | body radial gradient | 삭제 |
| `src/_pages/guardrails/ui/guardrails-page.tsx` | `정책 통제 영역`, page 부제, `로그인 사용자` | 삭제 |
| 같은 파일 | 카드 순번, `정책 그래프` | 삭제 |
| 같은 파일 | checkpoint 순서/ID 의미 | 유지·압축 |
| `src/_pages/guardrails/ui/guardrails-page.module.css` | 카드 gradient rail, shadow, hover 상승, 과한 radius | 삭제·축소 |
| `src/features/guardrail-editor/ui/editor-tabs.tsx` | `⌂`, 탭 순서 설명 | 삭제 |
| `src/features/guardrail-editor/ui/guardrail-editor.tsx` | 초기 `초안을 불러왔습니다…` | 삭제 |
| 같은 파일 | 자유 배치 두 문장 | `노드 배치는 저장되지 않습니다.`로 수정 |
| `src/features/guardrail-editor/ui/guardrail-overview.tsx` | `가드레일 개요`, 검사 지점 section의 eyebrow·두 설명 | 삭제 |
| 같은 파일 | 개요 metric 카드 | 값 유지, 카드 표현 삭제 |
| 같은 파일 | 검사 지점 구성 | 개요 첫 정보로 이동 |
| `src/features/guardrail-editor/model/catalog.ts` | 검사 지점·node의 일반 설명 문장 | 삭제 |
| `src/features/guardrail-editor/ui/node-inspector.tsx` | selected node 일반 설명, fixed checkpoint help | 삭제 |
| `src/features/guardrail-editor/ui/guardrail-test-panel.tsx` | drawer 부제, 모델 반복 help | 삭제 |
| 같은 파일 | `초안 강제 적용 테스트` 두 줄, `실제 호출 테스트` | 한 줄 context, `테스트`로 수정 |
| `src/entities/api-key/ui/app-connection-panel.tsx` | `OpenAI 호환 연결`, 기본 설명 부제 | 삭제 |
| `src/_pages/audit/ui/audit-page.tsx` | hero eyebrow·명령형 제목·부제·ClickHouse badge | 제목 `감사`만 유지 |
| 같은 파일 | summary metrics | 값 유지, 카드 표현 삭제 |
| 같은 파일 | `필터` + `범위 좁히기`, `이벤트`, `마지막 기록입니다.` | 중복 삭제 |
| 같은 파일 | `이벤트 상세`, `판정 근거 드릴다운`, 상세 부제, `원본 판정 필드` | 제목 `감사 이벤트`만 유지 |
| `src/_pages/audit/ui/audit-page.module.css` | 상세 section별 라운드 카드 | divider로 수정 |
| `src/_pages/providers/ui/providers-page.tsx` | `업스트림 라우팅`, page 부제, 카드 `프로바이더` | 삭제 |
| `src/_pages/providers/ui/providers-page.module.css` | gate 순번·gradient rails·점·hover 상승 | 삭제 |
| `src/_pages/api-keys/ui/api-keys-page.tsx` | `앱 크레덴셜`, page 부제, `로그인 사용자` | 삭제 |
| 같은 파일 | 연결 panel이 표보다 먼저 나오는 순서 | 표를 먼저 배치 |
| `src/shared/api/error-message.ts` 및 page/dialog fallback | `잠시 후 다시 시도하세요`, 포괄적 `연결 상태를 확인한 뒤…` | 원인/행동만 남김 |
| 모든 변경 파일 | aria-label, label, role, aria-live, focus·keyboard 동작 | 유지 |

이 목록 밖의 API 호출, query key, graph mapping, node/edge 순서, 저장·발행·삭제·테스트
동작은 변경하지 않는다.
