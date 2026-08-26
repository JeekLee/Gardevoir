import type { ConsoleApiError } from "./request";

const errorMessages: Record<string, string> = {
  "CONSOLE-001":
    "게이트웨이에 연결할 수 없습니다. 게이트웨이 상태와 네트워크 설정을 확인하세요.",
  "CONSOLE-002":
    "게이트웨이 응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.",
  "CONSOLE-003":
    "게이트웨이 응답 형식을 확인할 수 없습니다. 잠시 후 다시 시도하세요.",
  "CONSOLE-004":
    "게이트웨이가 요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.",
  "CONSOLE-005":
    "프로바이더 목록을 불러오지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.",
  "CONSOLE-006":
    "가드레일 실제 호출 테스트를 완료하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.",
  "AUTH-001": "세션이 만료되었습니다. 다시 로그인하세요.",
  "AUTH-002": "이 작업에는 관리자 권한이 필요합니다.",
  "SESSION-001": "세션이 만료되었습니다. 다시 로그인하세요.",
  "USER-001": "이메일 또는 비밀번호가 올바르지 않습니다.",
  "USER-002": "비활성화된 계정입니다. 관리자에게 문의하세요.",
  "PROVIDER-001": "프로바이더를 찾을 수 없습니다. 목록을 새로고침하세요.",
  "PROVIDER-002": "같은 이름의 프로바이더가 이미 있습니다.",
  "PROVIDER-003": "이 모델은 다른 프로바이더에 이미 연결되어 있습니다.",
  "PROVIDER-004": "모델을 하나 이상 추가하세요.",
  "PROVIDER-005": "요청한 모델을 제공하는 프로바이더가 없습니다.",
  "GUARDRAIL-001": "가드레일을 찾을 수 없습니다. 목록을 새로고침하세요.",
  "GUARDRAIL-002": "그래프에 순환 연결이 있습니다. 노드 연결을 확인하세요.",
  "GUARDRAIL-003": "존재하지 않는 노드로 이어진 연결이 있습니다.",
  "GUARDRAIL-004": "노드 ID가 중복되었습니다. 각 노드 ID를 고유하게 지정하세요.",
  "GUARDRAIL-005": "노드 설정이 올바르지 않습니다. 선택한 노드의 필드를 확인하세요.",
  "GUARDRAIL-006": "같은 이름의 가드레일이 이미 있습니다.",
  "GUARDRAIL-007": "발행본은 변경할 수 없습니다. 초안을 열어 수정하세요.",
  "GUARDRAIL-008": "편집할 초안이 없습니다. 가드레일 목록을 새로고침하세요.",
  "GUARDRAIL-009": "그래프 형식이 올바르지 않습니다. 노드와 연결을 확인하세요.",
  "GUARDRAIL-010": "가드레일 이름 형식이 올바르지 않습니다.",
  "GUARDRAIL-011":
    "다른 변경이 먼저 저장되었습니다. 최신 초안을 확인한 뒤 다시 시도하세요.",
  "GUARDRAIL-012": "노드의 입력 연결 수가 올바르지 않습니다.",
  "GUARDRAIL-013":
    "한 판정 노드에 서로 다른 검사 지점의 검사를 연결할 수 없습니다.",
  "GUARDRAIL-014":
    "마스킹 판정은 추출한 텍스트를 읽는 정규식 검사에만 연결할 수 있습니다.",
  "GUARDRAIL-015": "이 노드는 지정된 검사 지점에서만 사용할 수 있습니다.",
  "PROXY-001": "테스트할 가드레일을 지정하세요.",
  "PROXY-002": "테스트할 모델을 선택하세요.",
  INTERNAL: "게이트웨이가 요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.",
  VALIDATION: "입력 내용을 확인한 뒤 다시 시도하세요.",
  NOT_FOUND: "요청한 항목을 찾을 수 없습니다. 목록을 새로고침하세요.",
  UNAUTHORIZED: "세션이 만료되었습니다. 다시 로그인하세요.",
  FORBIDDEN: "이 작업을 수행할 권한이 없습니다.",
  CONFLICT: "현재 상태와 충돌했습니다. 최신 내용을 확인한 뒤 다시 시도하세요.",
};

export function consoleErrorMessage(
  error: Pick<ConsoleApiError, "code" | "httpStatus">,
  fallback?: string,
): string {
  const known = errorMessages[error.code];
  if (known) return known;
  if (fallback) return fallback;
  if (error.httpStatus === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (error.httpStatus === 403) return "이 작업을 수행할 권한이 없습니다.";
  if (error.httpStatus === 404) {
    return "요청한 항목을 찾을 수 없습니다. 목록을 새로고침하세요.";
  }
  if (error.httpStatus === 409) {
    return "현재 상태와 충돌했습니다. 최신 내용을 확인한 뒤 다시 시도하세요.";
  }
  if (error.httpStatus === 422) return "입력 내용을 확인한 뒤 다시 시도하세요.";
  return "요청을 완료하지 못했습니다. 잠시 후 다시 시도하세요.";
}

export function consoleErrorReference(
  error: Pick<ConsoleApiError, "code" | "requestId">,
): string {
  return error.requestId
    ? `참조: ${error.code} · 요청 ID ${error.requestId}`
    : `참조: ${error.code}`;
}
