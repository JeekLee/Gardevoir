import type {
  GuardrailAction,
  GuardrailGraph,
  GuardrailNode,
  GuardrailTestCheckpoint,
  GuardrailTestCheckpointName,
  GuardrailTestMode,
  GuardrailTestResult,
} from "@/src/entities/guardrail";
import type { ProviderSummary } from "@/src/entities/provider";

export type ProviderModelOption = {
  model: string;
  provider: string;
};

export type FiredNodeTrace = {
  code: string;
  verdict: GuardrailNode;
  upstream: GuardrailNode[];
};

export type DiffPart = {
  text: string;
  changed: boolean;
};

export type TextDiff = {
  raw: DiffPart[];
  applied: DiffPart[];
  changed: boolean;
};

export type PlaygroundRun = {
  result: GuardrailTestResult;
  graph: GuardrailGraph;
  mode: GuardrailTestMode;
};

const actionSeverity: Record<GuardrailAction, number> = {
  allow: 0,
  mask: 1,
  block: 2,
};

const checkpointOrder: GuardrailTestCheckpointName[] = [
  "input",
  "toolResult",
  "output",
  "toolCall",
];

const maskPlaceholder = "[개인정보 삭제됨]";

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

export function firedNodeTraces(
  graph: GuardrailGraph,
  checksFired: string[],
  checkpoint?: GuardrailTestCheckpointName,
  rawText?: string | null,
): FiredNodeTrace[] {
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const incoming = new Map<string, string[]>();
  for (const edge of graph.edges) {
    incoming.set(edge.dst, [...(incoming.get(edge.dst) ?? []), edge.src]);
  }

  const trace = (node: GuardrailNode, code: string): FiredNodeTrace => {
    const visited = new Set<string>();
    const ordered: GuardrailNode[] = [];
    const visit = (nodeId: string) => {
      for (const sourceId of incoming.get(nodeId) ?? []) {
        if (visited.has(sourceId)) continue;
        visited.add(sourceId);
        visit(sourceId);
        const source = nodesById.get(sourceId);
        if (source) ordered.push(source);
      }
    };
    visit(node.id);
    return { code, verdict: node, upstream: ordered };
  };

  const verdicts = graph.nodes.filter((node) => node.type === "verdict");
  const matches = checksFired.flatMap((code) => {
    const exact = verdicts.filter((node) => node.id === code);
    const candidates = exact.length > 0
      ? exact
      : verdicts.filter((node) => verdictCode(node) === code);
    return candidates.map((node) => trace(node, code));
  });
  const atCheckpoint = checkpoint
    ? narrowToCheckpoint(matches, checkpoint)
    : matches;
  return rawText ? narrowToMatchingRegex(atCheckpoint, rawText) : atCheckpoint;
}

export function actionForCheckpoint(
  graph: GuardrailGraph,
  checkpoint: GuardrailTestCheckpoint,
  mode: GuardrailTestMode,
  checkpointName?: GuardrailTestCheckpointName,
): GuardrailAction {
  if (mode !== "dry-run") return checkpoint.action;
  const firedActions = firedNodeTraces(
    graph,
    checkpoint.checksFired,
    checkpointName,
    checkpoint.rawText,
  ).map(({ verdict }) => verdictAction(verdict));
  return strongestAction([checkpoint.action, ...firedActions]);
}

export function overallAction(run: PlaygroundRun): GuardrailAction {
  return strongestAction(
    checkpointOrder.map((checkpoint) =>
      actionForCheckpoint(
        run.graph,
        run.result.checkpoints[checkpoint],
        run.mode,
        checkpoint,
      ),
    ),
  );
}

export function blockedCheckpoint(
  run: PlaygroundRun,
): GuardrailTestCheckpointName | null {
  if (run.result.blockedAt) return run.result.blockedAt;
  if (run.mode !== "dry-run") return null;
  return (
    checkpointOrder.find(
      (checkpoint) =>
        actionForCheckpoint(
          run.graph,
          run.result.checkpoints[checkpoint],
          run.mode,
          checkpoint,
        ) === "block",
    ) ?? null
  );
}

export function diffText(raw: string, applied: string): TextDiff {
  if (raw === applied) {
    return {
      raw: [{ text: raw, changed: false }],
      applied: [{ text: applied, changed: false }],
      changed: false,
    };
  }

  const masked = diffMaskPlaceholders(raw, applied);
  if (masked) return masked;

  let prefix = 0;
  const prefixLimit = Math.min(raw.length, applied.length);
  while (prefix < prefixLimit && raw[prefix] === applied[prefix]) prefix += 1;

  let suffix = 0;
  while (
    suffix < raw.length - prefix &&
    suffix < applied.length - prefix &&
    raw[raw.length - suffix - 1] === applied[applied.length - suffix - 1]
  ) {
    suffix += 1;
  }

  return {
    raw: compactParts([
      { text: raw.slice(0, prefix), changed: false },
      {
        text: raw.slice(prefix, suffix ? raw.length - suffix : raw.length),
        changed: true,
      },
      { text: suffix ? raw.slice(-suffix) : "", changed: false },
    ]),
    applied: compactParts([
      { text: applied.slice(0, prefix), changed: false },
      {
        text: applied.slice(
          prefix,
          suffix ? applied.length - suffix : applied.length,
        ),
        changed: true,
      },
      { text: suffix ? applied.slice(-suffix) : "", changed: false },
    ]),
    changed: true,
  };
}

function diffMaskPlaceholders(raw: string, applied: string): TextDiff | null {
  if (!applied.includes(maskPlaceholder)) return null;

  const literals = applied.split(maskPlaceholder);
  const rawParts: DiffPart[] = [];
  const appliedParts: DiffPart[] = [];
  let cursor = 0;

  for (let index = 0; index < literals.length; index += 1) {
    const literal = literals[index];
    if (index === 0) {
      if (!raw.startsWith(literal)) return null;
    } else {
      const next = literal ? raw.indexOf(literal, cursor) : raw.length;
      if (next < cursor) return null;
      rawParts.push({ text: raw.slice(cursor, next), changed: true });
      appliedParts.push({ text: maskPlaceholder, changed: true });
      cursor = next;
    }

    rawParts.push({ text: literal, changed: false });
    appliedParts.push({ text: literal, changed: false });
    cursor += literal.length;
  }

  if (cursor < raw.length) rawParts.push({ text: raw.slice(cursor), changed: true });
  return {
    raw: compactParts(rawParts),
    applied: compactParts(appliedParts),
    changed: true,
  };
}

function strongestAction(actions: GuardrailAction[]): GuardrailAction {
  return actions.reduce((strongest, action) =>
    actionSeverity[action] > actionSeverity[strongest] ? action : strongest,
  );
}

function verdictCode(node: GuardrailNode): string {
  const code = node.config.code;
  return typeof code === "string" && code ? code : node.id;
}

function verdictAction(node: GuardrailNode): GuardrailAction {
  const action = node.config.action;
  return action === "block" || action === "mask" ? action : "allow";
}

function narrowToCheckpoint(
  traces: FiredNodeTrace[],
  checkpoint: GuardrailTestCheckpointName,
): FiredNodeTrace[] {
  const matching = traces.filter((trace) => {
    const declared = trace.upstream
      .map((node) => node.config.checkpoint)
      .filter((value): value is string => typeof value === "string");
    return declared.includes(checkpoint);
  });
  return matching.length > 0 ? matching : traces;
}

function narrowToMatchingRegex(
  traces: FiredNodeTrace[],
  rawText: string,
): FiredNodeTrace[] {
  if (traces.length < 2) return traces;
  const matching = traces.filter((trace) =>
    trace.upstream.some((node) => {
      if (node.type !== "regex" || typeof node.config.pattern !== "string") {
        return false;
      }
      try {
        return new RegExp(node.config.pattern).test(rawText);
      } catch {
        return false;
      }
    }),
  );
  return matching.length > 0 ? matching : traces;
}

function compactParts(parts: DiffPart[]): DiffPart[] {
  return parts.filter((part) => part.text.length > 0);
}
