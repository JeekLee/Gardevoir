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
  unmaskable?: number;
};

export type GuardrailTestStreamEvent =
  | { type: "delta"; content: string }
  | { type: "result"; result: GuardrailTestResult };

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
      input: parseCheckpoint(value.checkpoints.input),
      toolResult: parseCheckpoint(value.checkpoints.toolResult),
      output: parseCheckpoint(value.checkpoints.output),
      toolCall: parseCheckpoint(value.checkpoints.toolCall),
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
    unmaskable:
      typeof value.unmaskable === "number" ? value.unmaskable : undefined,
  };
}

export class GuardrailTestStreamParser {
  readonly #decoder = new TextDecoder();
  #buffer = "";

  push(chunk: Uint8Array): GuardrailTestStreamEvent[] {
    this.#buffer += this.#decoder.decode(chunk, { stream: true });
    return this.#drain(false);
  }

  finish(): GuardrailTestStreamEvent[] {
    this.#buffer += this.#decoder.decode();
    return this.#drain(true);
  }

  #drain(flush: boolean): GuardrailTestStreamEvent[] {
    this.#buffer = this.#buffer.replaceAll("\r\n", "\n");
    const events: GuardrailTestStreamEvent[] = [];
    while (true) {
      const boundary = this.#buffer.indexOf("\n\n");
      if (boundary < 0) break;
      const block = this.#buffer.slice(0, boundary);
      this.#buffer = this.#buffer.slice(boundary + 2);
      const event = parseStreamBlock(block);
      if (event) events.push(event);
    }
    if (flush && this.#buffer.trim()) {
      const event = parseStreamBlock(this.#buffer);
      if (event) events.push(event);
      this.#buffer = "";
    }
    return events;
  }
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

function parseStreamBlock(block: string): GuardrailTestStreamEvent | null {
  let eventName = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      data.push(line.slice("data:".length).trimStart());
    }
  }
  if (data.length === 0) return null;

  const payload = data.join("\n");
  if (payload === "[DONE]") return null;

  let value: unknown;
  try {
    value = JSON.parse(payload);
  } catch {
    throw new Error("Invalid guardrail test stream event");
  }

  if (eventName === "result") {
    return { type: "result", result: parseGuardrailTestResult(value) };
  }

  if (!isRecord(value) || !Array.isArray(value.choices)) return null;
  const content = value.choices
    .map((choice) =>
      isRecord(choice) &&
      isRecord(choice.delta) &&
      typeof choice.delta.content === "string"
        ? choice.delta.content
        : "",
    )
    .join("");
  return content ? { type: "delta", content } : null;
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
