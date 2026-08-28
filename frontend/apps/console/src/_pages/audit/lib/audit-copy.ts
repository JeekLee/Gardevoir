import type { AuditAction, AuditCheckpoint } from "@/src/entities/audit";

export const actionCopy: Record<AuditAction, string> = {
  allow: "허용",
  mask: "마스킹",
  blocked: "차단",
  approval_required: "승인 필요",
};

export const checkpointCopy: Record<AuditCheckpoint, string> = {
  "": "검사 없음",
  input: "입력",
  tool_result: "툴 결과",
  output: "출력",
  tool_call: "툴 호출",
};
