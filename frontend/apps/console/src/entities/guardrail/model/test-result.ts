import type { GuardrailAction } from "./guardrail";

export type GuardrailTestEvidence = {
  tool: string;
  arguments: string[];
};

export type GuardrailTestCheckpoint = {
  ran: boolean;
  action: GuardrailAction;
  checksFired: string[];
  masked: boolean;
  evidence: GuardrailTestEvidence[];
  tier: string;
  rawText: string | null;
  appliedText: string | null;
};

export type GuardrailTestCheckpointName =
  | "input"
  | "toolResult"
  | "output"
  | "toolCall";

export type GuardrailTestResult = {
  guardrail: string;
  version: string;
  model: string;
  checkpoints: {
    input: GuardrailTestCheckpoint;
    toolResult: GuardrailTestCheckpoint;
    output: GuardrailTestCheckpoint;
    toolCall: GuardrailTestCheckpoint;
  };
  overallAction: GuardrailAction;
  blocked: boolean;
  blockedAt: GuardrailTestCheckpointName | null;
  blockedReason: string | null;
  rawContent: string;
  appliedContent: string;
  toolCalls: Record<string, unknown>[];
  auditId: null;
  latencyMs: number;
  unmaskable: number;
};

export type GuardrailTestPre = Pick<
  GuardrailTestResult["checkpoints"],
  "input" | "toolResult"
>;

export type GuardrailTestMode = "enforce" | "dry-run";

export type GuardrailTestContentPart =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string } };

export type GuardrailTestMessage =
  | {
      role: "user";
      content: string | GuardrailTestContentPart[];
    }
  | {
      role: "tool";
      content: string;
      tool_call_id: string;
    };

export type GuardrailTestToolChoice =
  | "auto"
  | "none"
  | {
      type: "function";
      function: { name: string };
    };

export type GuardrailTestInput = {
  model: string;
  messages: GuardrailTestMessage[];
  version: string;
  mode: GuardrailTestMode;
  tools?: Record<string, unknown>[];
  toolChoice?: GuardrailTestToolChoice;
};

export function parseGuardrailTestResult(value: unknown): GuardrailTestResult {
  if (
    !isRecord(value) ||
    typeof value.guardrail !== "string" ||
    typeof value.version !== "string" ||
    typeof value.model !== "string" ||
    !isGuardrailAction(value.overallAction) ||
    !isRecord(value.checkpoints) ||
    typeof value.blocked !== "boolean" ||
    (value.blockedAt !== null && !isCheckpointName(value.blockedAt)) ||
    (value.blockedReason !== null && typeof value.blockedReason !== "string") ||
    typeof value.rawContent !== "string" ||
    typeof value.appliedContent !== "string" ||
    !Array.isArray(value.toolCalls) ||
    !value.toolCalls.every(isRecord) ||
    value.auditId !== null ||
    typeof value.latencyMs !== "number" ||
    (value.unmaskable !== undefined &&
      (typeof value.unmaskable !== "number" ||
        !Number.isInteger(value.unmaskable) ||
        value.unmaskable < 0))
  ) {
    throw new Error("Invalid guardrail test response");
  }

  return {
    guardrail: value.guardrail,
    version: value.version,
    model: value.model,
    checkpoints: {
      input: parseGuardrailTestCheckpoint(value.checkpoints.input),
      toolResult: parseGuardrailTestCheckpoint(value.checkpoints.toolResult),
      output: parseGuardrailTestCheckpoint(value.checkpoints.output),
      toolCall: parseGuardrailTestCheckpoint(value.checkpoints.toolCall),
    },
    overallAction: value.overallAction,
    blocked: value.blocked,
    blockedAt: value.blockedAt,
    blockedReason: value.blockedReason,
    rawContent: value.rawContent,
    appliedContent: value.appliedContent,
    toolCalls: value.toolCalls,
    auditId: null,
    latencyMs: value.latencyMs,
    unmaskable: typeof value.unmaskable === "number" ? value.unmaskable : 0,
  };
}

export function parseGuardrailTestPre(value: unknown): GuardrailTestPre {
  if (!isRecord(value)) {
    throw new Error("Invalid guardrail test pre event");
  }
  return {
    input: parseGuardrailTestCheckpoint(value.input),
    toolResult: parseGuardrailTestCheckpoint(value.toolResult),
  };
}

function parseGuardrailTestCheckpoint(
  value: unknown,
): GuardrailTestCheckpoint {
  if (
    !isRecord(value) ||
    typeof value.ran !== "boolean" ||
    !isGuardrailAction(value.action) ||
    !isStringArray(value.checksFired) ||
    typeof value.masked !== "boolean" ||
    !Array.isArray(value.evidence) ||
    typeof value.tier !== "string" ||
    !isNullableString(value.rawText) ||
    !isNullableString(value.appliedText)
  ) {
    throw new Error("Invalid guardrail test checkpoint");
  }
  return {
    ran: value.ran,
    action: value.action,
    checksFired: value.checksFired,
    masked: value.masked,
    evidence: value.evidence.map(parseEvidence),
    tier: value.tier,
    rawText: value.rawText,
    appliedText: value.appliedText,
  };
}

function parseEvidence(value: unknown): GuardrailTestEvidence {
  if (
    !isRecord(value) ||
    typeof value.tool !== "string" ||
    !isStringArray(value.arguments)
  ) {
    throw new Error("Invalid guardrail test evidence");
  }
  return { tool: value.tool, arguments: value.arguments };
}

function isGuardrailAction(value: unknown): value is GuardrailAction {
  return value === "block" || value === "mask" || value === "allow";
}

function isCheckpointName(
  value: unknown,
): value is GuardrailTestCheckpointName {
  return (
    value === "input" ||
    value === "toolResult" ||
    value === "output" ||
    value === "toolCall"
  );
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
