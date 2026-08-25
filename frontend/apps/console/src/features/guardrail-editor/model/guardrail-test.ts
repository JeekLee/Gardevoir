import type {
  GuardrailAction,
  GuardrailGraph,
} from "@/src/entities/guardrail";
import type { ProviderSummary } from "@/src/entities/provider";

export type GuardrailTestEvidence = {
  tool: string;
  arguments: string[];
};

export type GuardrailTestCheckpoint = {
  ran: boolean;
  wouldHave: GuardrailAction | null;
  checksFired: string[];
  masked: boolean;
  evidence: GuardrailTestEvidence[];
  tier: string;
};

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
  overallWouldHave: GuardrailAction;
  modelResponse: {
    content: string;
    toolCalls: Record<string, unknown>[];
    maskedPreview: string | null;
  };
  auditId: string | null;
  latencyMs: number;
};

export type ProviderModelOption = {
  model: string;
  provider: string;
};

export type TestHighlights = {
  fired: string[];
  upstream: string[];
};

export function parseGuardrailTestResult(value: unknown): GuardrailTestResult {
  if (
    !isRecord(value) ||
    typeof value.guardrail !== "string" ||
    typeof value.version !== "string" ||
    typeof value.model !== "string" ||
    !isGuardrailAction(value.overallWouldHave) ||
    !isRecord(value.checkpoints) ||
    !isRecord(value.modelResponse) ||
    typeof value.modelResponse.content !== "string" ||
    !Array.isArray(value.modelResponse.toolCalls) ||
    !value.modelResponse.toolCalls.every(isRecord) ||
    (value.modelResponse.maskedPreview !== null &&
      typeof value.modelResponse.maskedPreview !== "string") ||
    (value.auditId !== null && typeof value.auditId !== "string") ||
    typeof value.latencyMs !== "number"
  ) {
    throw new Error("Invalid guardrail test response");
  }

  return {
    guardrail: value.guardrail,
    version: value.version,
    model: value.model,
    checkpoints: {
      input: parseCheckpoint(value.checkpoints.input),
      toolResult: parseCheckpoint(value.checkpoints.toolResult),
      output: parseCheckpoint(value.checkpoints.output),
      toolCall: parseCheckpoint(value.checkpoints.toolCall),
    },
    overallWouldHave: value.overallWouldHave,
    modelResponse: {
      content: value.modelResponse.content,
      toolCalls: value.modelResponse.toolCalls,
      maskedPreview: value.modelResponse.maskedPreview,
    },
    auditId: value.auditId,
    latencyMs: value.latencyMs,
  };
}

export function providerModelOptions(
  providers: ProviderSummary[],
): ProviderModelOption[] {
  const seen = new Set<string>();
  const options: ProviderModelOption[] = [];
  for (const provider of providers) {
    for (const model of provider.models) {
      if (seen.has(model)) continue;
      seen.add(model);
      options.push({ model, provider: provider.name });
    }
  }
  return options;
}

export function firedCheckCodes(result: GuardrailTestResult): string[] {
  return [
    ...result.checkpoints.input.checksFired,
    ...result.checkpoints.toolResult.checksFired,
    ...result.checkpoints.output.checksFired,
    ...result.checkpoints.toolCall.checksFired,
  ];
}

export function testHighlights(
  graph: GuardrailGraph,
  checksFired: string[],
): TestHighlights {
  const codes = new Set(checksFired);
  const fired = new Set(
    graph.nodes
      .filter(
        (node) =>
          node.type === "verdict" &&
          typeof node.config.code === "string" &&
          codes.has(node.config.code),
      )
      .map((node) => node.id),
  );
  const incoming = new Map<string, string[]>();
  for (const edge of graph.edges) {
    incoming.set(edge.dst, [...(incoming.get(edge.dst) ?? []), edge.src]);
  }

  const upstream = new Set<string>();
  const queue = [...fired];
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) continue;
    for (const source of incoming.get(current) ?? []) {
      if (fired.has(source) || upstream.has(source)) continue;
      upstream.add(source);
      queue.push(source);
    }
  }

  return { fired: [...fired], upstream: [...upstream] };
}

function parseCheckpoint(value: unknown): GuardrailTestCheckpoint {
  if (
    !isRecord(value) ||
    typeof value.ran !== "boolean" ||
    (value.wouldHave !== null && !isGuardrailAction(value.wouldHave)) ||
    !isStringArray(value.checksFired) ||
    typeof value.masked !== "boolean" ||
    !Array.isArray(value.evidence) ||
    typeof value.tier !== "string"
  ) {
    throw new Error("Invalid guardrail test checkpoint");
  }
  return {
    ran: value.ran,
    wouldHave: value.wouldHave,
    checksFired: value.checksFired,
    masked: value.masked,
    evidence: value.evidence.map(parseEvidence),
    tier: value.tier,
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

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
