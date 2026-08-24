export const checkpoints = [
  "input",
  "tool_result",
  "tool_call",
  "output",
] as const;

export type Checkpoint = (typeof checkpoints)[number];

export const nodeTypes = [
  "extract",
  "regex",
  "length",
  "transform",
  "verdict",
  "taint",
  "all",
  "side_effect",
  "provenance",
] as const;

export type GuardrailNodeType = (typeof nodeTypes)[number];

export type GuardrailNode = {
  id: string;
  type: GuardrailNodeType;
  config: Record<string, unknown>;
};

export type GuardrailEdge = {
  src: string;
  dst: string;
};

export type GuardrailGraph = {
  nodes: GuardrailNode[];
  edges: GuardrailEdge[];
};

export type GuardrailSummary = {
  name: string;
  latestVersionNumber: number | null;
  hasDraft: boolean;
  updatedAt: string;
};

export type GuardrailPage = {
  items: GuardrailSummary[];
  total: number;
};

export type GuardrailDetail = {
  name: string;
  version: string;
  versionNumber: number | null;
  graph: GuardrailGraph;
  createdAt: string;
  updatedAt: string;
};

export function parseGuardrailPage(value: unknown): GuardrailPage {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    typeof value.total !== "number"
  ) {
    throw new Error("Invalid guardrail list response");
  }

  return {
    items: value.items.map(parseGuardrailSummary),
    total: value.total,
  };
}

export function parseGuardrailDetail(value: unknown): GuardrailDetail {
  if (
    !isRecord(value) ||
    typeof value.name !== "string" ||
    typeof value.version !== "string" ||
    (value.versionNumber !== null && typeof value.versionNumber !== "number") ||
    typeof value.createdAt !== "string" ||
    typeof value.updatedAt !== "string"
  ) {
    throw new Error("Invalid guardrail response");
  }

  return {
    name: value.name,
    version: value.version,
    versionNumber: value.versionNumber,
    graph: parseGuardrailGraph(value.graph),
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  };
}

export function parseGuardrailGraph(value: unknown): GuardrailGraph {
  if (
    !isRecord(value) ||
    !Array.isArray(value.nodes) ||
    !Array.isArray(value.edges)
  ) {
    throw new Error("Invalid guardrail graph response");
  }

  return {
    nodes: value.nodes.map(parseGuardrailNode),
    edges: value.edges.map(parseGuardrailEdge),
  };
}

function parseGuardrailSummary(value: unknown): GuardrailSummary {
  if (
    !isRecord(value) ||
    typeof value.name !== "string" ||
    (value.latestVersionNumber !== null &&
      typeof value.latestVersionNumber !== "number") ||
    typeof value.hasDraft !== "boolean" ||
    typeof value.updatedAt !== "string"
  ) {
    throw new Error("Invalid guardrail summary response");
  }

  return {
    name: value.name,
    latestVersionNumber: value.latestVersionNumber,
    hasDraft: value.hasDraft,
    updatedAt: value.updatedAt,
  };
}

function parseGuardrailNode(value: unknown): GuardrailNode {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isGuardrailNodeType(value.type) ||
    !isRecord(value.config)
  ) {
    throw new Error("Invalid guardrail node response");
  }

  return {
    id: value.id,
    type: value.type,
    config: { ...value.config },
  };
}

function parseGuardrailEdge(value: unknown): GuardrailEdge {
  if (
    !isRecord(value) ||
    typeof value.src !== "string" ||
    typeof value.dst !== "string"
  ) {
    throw new Error("Invalid guardrail edge response");
  }

  return { src: value.src, dst: value.dst };
}

function isGuardrailNodeType(value: unknown): value is GuardrailNodeType {
  return typeof value === "string" && nodeTypes.some((type) => type === value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
