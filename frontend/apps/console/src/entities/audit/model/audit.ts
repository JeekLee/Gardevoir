export const auditActions = [
  "allow",
  "mask",
  "blocked",
  "approval_required",
] as const;
export type AuditAction = (typeof auditActions)[number];

export const auditCheckpoints = [
  "",
  "input",
  "tool_result",
  "output",
  "tool_call",
] as const;
export type AuditCheckpoint = (typeof auditCheckpoints)[number];

export const auditModes = ["enforce", "dry-run"] as const;
export type AuditMode = (typeof auditModes)[number];

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type AuditFilters = {
  appName?: string;
  guardrail?: string;
  action?: AuditAction;
  checkpoint?: Exclude<AuditCheckpoint, "">;
  mode?: AuditMode;
  tainted?: boolean;
  from?: string;
  to?: string;
};

export type AuditEventSummary = {
  id: string;
  createdAt: string;
  appName: string;
  guardrail: string;
  guardrailVersion: number;
  mode: AuditMode;
  action: AuditAction;
  checkpoint: AuditCheckpoint;
  checksFired: string[];
  tierReached: string;
  tainted: boolean;
  latencyMs: number;
  model: string;
};

export type AuditEventDetail = AuditEventSummary & {
  requestId: string;
  apiKeyId: string;
  verdicts: JsonValue;
  promptTokens: number;
  completionTokens: number;
};

export type AuditEventPage = {
  items: AuditEventSummary[];
  nextCursor: string | null;
};

export type AuditSummary = {
  countsByAction: Record<string, number>;
  latencyP50: number;
  latencyP95: number;
  total: number;
};

export function parseAuditEventPage(value: unknown): AuditEventPage {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    (value.nextCursor !== null && typeof value.nextCursor !== "string")
  ) {
    throw new Error("Invalid audit list response");
  }
  return {
    items: value.items.map(parseAuditEventSummary),
    nextCursor: value.nextCursor,
  };
}

export function parseAuditEventDetail(value: unknown): AuditEventDetail {
  const summary = parseAuditEventSummary(value);
  if (
    !isRecord(value) ||
    typeof value.requestId !== "string" ||
    typeof value.apiKeyId !== "string" ||
    !isJsonValue(value.verdicts) ||
    !isCount(value.promptTokens) ||
    !isCount(value.completionTokens)
  ) {
    throw new Error("Invalid audit detail response");
  }
  return {
    ...summary,
    requestId: value.requestId,
    apiKeyId: value.apiKeyId,
    verdicts: cloneJson(value.verdicts),
    promptTokens: value.promptTokens,
    completionTokens: value.completionTokens,
  };
}

export function parseAuditSummary(value: unknown): AuditSummary {
  if (
    !isRecord(value) ||
    !isRecord(value.countsByAction) ||
    !isFiniteNumber(value.latencyP50) ||
    !isFiniteNumber(value.latencyP95) ||
    !isCount(value.total)
  ) {
    throw new Error("Invalid audit summary response");
  }
  const countsByAction: Record<string, number> = {};
  for (const [action, count] of Object.entries(value.countsByAction)) {
    if (!isCount(count)) throw new Error("Invalid audit summary response");
    countsByAction[action] = count;
  }
  return {
    countsByAction,
    latencyP50: value.latencyP50,
    latencyP95: value.latencyP95,
    total: value.total,
  };
}

function parseAuditEventSummary(value: unknown): AuditEventSummary {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.createdAt !== "string" ||
    typeof value.appName !== "string" ||
    typeof value.guardrail !== "string" ||
    !isCount(value.guardrailVersion) ||
    !isAuditMode(value.mode) ||
    !isAuditAction(value.action) ||
    !isAuditCheckpoint(value.checkpoint) ||
    !Array.isArray(value.checksFired) ||
    !value.checksFired.every((check) => typeof check === "string") ||
    typeof value.tierReached !== "string" ||
    typeof value.tainted !== "boolean" ||
    !isFiniteNumber(value.latencyMs) ||
    typeof value.model !== "string"
  ) {
    throw new Error("Invalid audit event response");
  }
  return {
    id: value.id,
    createdAt: value.createdAt,
    appName: value.appName,
    guardrail: value.guardrail,
    guardrailVersion: value.guardrailVersion,
    mode: value.mode,
    action: value.action,
    checkpoint: value.checkpoint,
    checksFired: [...value.checksFired],
    tierReached: value.tierReached,
    tainted: value.tainted,
    latencyMs: value.latencyMs,
    model: value.model,
  };
}

function isAuditAction(value: unknown): value is AuditAction {
  return (
    typeof value === "string" &&
    auditActions.some((action) => action === value)
  );
}

function isAuditCheckpoint(value: unknown): value is AuditCheckpoint {
  return (
    typeof value === "string" &&
    auditCheckpoints.some((checkpoint) => checkpoint === value)
  );
}

function isAuditMode(value: unknown): value is AuditMode {
  return typeof value === "string" && auditModes.some((mode) => mode === value);
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "boolean" ||
    typeof value === "string"
  ) {
    return true;
  }
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function cloneJson(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(cloneJson);
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, cloneJson(item)]),
    );
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
