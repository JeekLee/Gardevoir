import {
  parseGuardrailTestPre,
  parseGuardrailTestResult,
  type GuardrailGraph,
  type GuardrailTestCheckpoint,
  type GuardrailTestPre,
  type GuardrailTestResult,
} from "@/src/entities/guardrail";
import type { ProviderSummary } from "@/src/entities/provider";

export { parseGuardrailTestResult };
export type {
  GuardrailTestCheckpoint,
  GuardrailTestPre,
  GuardrailTestResult,
};

export type GuardrailTestStreamEvent =
  | { type: "pre"; pre: GuardrailTestPre }
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
        (node) => {
          if (node.type !== "verdict") return false;
          const code =
            typeof node.config.code === "string" && node.config.code
              ? node.config.code
              : node.id;
          return codes.has(code);
        },
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
  if (eventName === "pre") {
    return { type: "pre", pre: parseGuardrailTestPre(value) };
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
