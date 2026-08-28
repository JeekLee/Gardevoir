export const checkpoints = [
  "input",
  "tool_result",
  "tool_call",
  "output",
] as const;

export type Checkpoint = (typeof checkpoints)[number];

export const guardrailActions = ["block", "mask", "allow"] as const;

export type GuardrailAction = (typeof guardrailActions)[number];

export const verdictCombines = ["any", "all"] as const;

export type VerdictCombine = (typeof verdictCombines)[number];

export const modelStrictnesses = ["strict", "balanced", "lenient"] as const;

export type ModelStrictness = (typeof modelStrictnesses)[number];

export const nodeTypes = [
  "extract",
  "tool_extract",
  "regex",
  "model",
  "not",
  "transform",
  "verdict",
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
  description: string;
  latestVersionNumber: number | null;
  hasDraft: boolean;
  updatedAt: string;
  checkpoints: Checkpoint[];
  actions: GuardrailAction[];
  checkCount: number;
  verdictCount: number;
};

export type GuardrailPage = {
  items: GuardrailSummary[];
  total: number;
};

export type GuardrailVersionSummary = {
  versionNumber: number;
  publishedAt: string;
  description: string;
  nodeCount: number;
  verdictCount: number;
};

export type GuardrailVersionPage = {
  items: GuardrailVersionSummary[];
  total: number;
};

export type GuardrailDetail = {
  name: string;
  version: string;
  versionNumber: number | null;
  description: string;
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
    typeof value.description !== "string" ||
    typeof value.createdAt !== "string" ||
    typeof value.updatedAt !== "string"
  ) {
    throw new Error("Invalid guardrail response");
  }

  return {
    name: value.name,
    version: value.version,
    versionNumber: value.versionNumber,
    description: value.description,
    graph: parseGuardrailGraph(value.graph),
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  };
}

export function parseGuardrailVersionPage(value: unknown): GuardrailVersionPage {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    typeof value.total !== "number"
  ) {
    throw new Error("Invalid guardrail version list response");
  }
  return {
    items: value.items.map(parseGuardrailVersionSummary),
    total: value.total,
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
    typeof value.description !== "string" ||
    (value.latestVersionNumber !== null &&
      typeof value.latestVersionNumber !== "number") ||
    typeof value.hasDraft !== "boolean" ||
    typeof value.updatedAt !== "string"
  ) {
    throw new Error("Invalid guardrail summary response");
  }

  return {
    name: value.name,
    description: value.description,
    latestVersionNumber: value.latestVersionNumber,
    hasDraft: value.hasDraft,
    updatedAt: value.updatedAt,
    checkpoints: parseCheckpoints(value.checkpoints),
    actions: parseActions(value.actions),
    checkCount: parseCount(value.checkCount),
    verdictCount: parseCount(value.verdictCount),
  };
}

function parseGuardrailVersionSummary(value: unknown): GuardrailVersionSummary {
  if (
    !isRecord(value) ||
    !Number.isInteger(value.versionNumber) ||
    typeof value.versionNumber !== "number" ||
    value.versionNumber < 1 ||
    typeof value.publishedAt !== "string" ||
    typeof value.description !== "string" ||
    !isNonNegativeInteger(value.nodeCount) ||
    !isNonNegativeInteger(value.verdictCount)
  ) {
    throw new Error("Invalid guardrail version summary response");
  }
  return {
    versionNumber: value.versionNumber,
    publishedAt: value.publishedAt,
    description: value.description,
    nodeCount: value.nodeCount,
    verdictCount: value.verdictCount,
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

function parseCheckpoints(value: unknown): Checkpoint[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || !value.every(isCheckpoint)) {
    throw new Error("Invalid guardrail summary checkpoints");
  }
  return [...value];
}

function parseActions(value: unknown): GuardrailAction[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || !value.every(isGuardrailAction)) {
    throw new Error("Invalid guardrail summary actions");
  }
  return [...value];
}

function parseCount(value: unknown): number {
  if (value === undefined) return 0;
  if (!Number.isInteger(value) || typeof value !== "number" || value < 0) {
    throw new Error("Invalid guardrail summary count");
  }
  return value;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isCheckpoint(value: unknown): value is Checkpoint {
  return (
    typeof value === "string" &&
    checkpoints.some((checkpoint) => checkpoint === value)
  );
}

function isGuardrailAction(value: unknown): value is GuardrailAction {
  return (
    typeof value === "string" &&
    guardrailActions.some((action) => action === value)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
