import type {
  Checkpoint,
  GuardrailNode,
  GuardrailNodeType,
} from "@/src/entities/guardrail";

export const checkpointMeta: Record<
  Checkpoint,
  {
    index: "①" | "②" | "④" | "③";
    label: string;
    shortLabel: string;
    description: string;
    x: number;
  }
> = {
  input: {
    index: "①",
    label: "Input",
    shortLabel: "User message",
    description: "Intent enters",
    x: 0,
  },
  tool_result: {
    index: "②",
    label: "Tool result",
    shortLabel: "Untrusted data",
    description: "External data enters",
    x: 340,
  },
  tool_call: {
    index: "④",
    label: "Tool call",
    shortLabel: "Agent action",
    description: "Side effects leave",
    x: 680,
  },
  output: {
    index: "③",
    label: "Output",
    shortLabel: "Model response",
    description: "Response returns",
    x: 1020,
  },
};

export type NodeCatalogItem = {
  type: GuardrailNodeType;
  label: string;
  category: "Source" | "Check" | "Logic" | "Decision" | "Action control";
  description: string;
  defaultConfig: (checkpoint: Checkpoint) => Record<string, unknown>;
};

export const nodeCatalog: NodeCatalogItem[] = [
  {
    type: "extract",
    label: "Extract",
    category: "Source",
    description: "Read text at this checkpoint.",
    defaultConfig: (checkpoint) => ({ checkpoint }),
  },
  {
    type: "regex",
    label: "Regex",
    category: "Check",
    description: "Match an RE2 policy pattern.",
    defaultConfig: () => ({ pattern: "" }),
  },
  {
    type: "length",
    label: "Length",
    category: "Check",
    description: "Check a maximum character count.",
    defaultConfig: () => ({ max_chars: 1_000 }),
  },
  {
    type: "transform",
    label: "Transform",
    category: "Check",
    description: "Normalize text before another check.",
    defaultConfig: () => ({ op: "lower" }),
  },
  {
    type: "verdict",
    label: "Verdict",
    category: "Decision",
    description: "Block, mask, or allow when inputs match.",
    defaultConfig: () => ({
      action: "block",
      code: "policy-match",
      decision: "conclusive",
    }),
  },
  {
    type: "taint",
    label: "Taint",
    category: "Action control",
    description: "Track whether tool data entered the conversation.",
    defaultConfig: (checkpoint) => ({ checkpoint }),
  },
  {
    type: "all",
    label: "All",
    category: "Logic",
    description: "Require every connected check to match.",
    defaultConfig: () => ({}),
  },
  {
    type: "side_effect",
    label: "Side effect",
    category: "Action control",
    description: "Treat every tool outside the read-only list as risky.",
    defaultConfig: () => ({ checkpoint: "tool_call", read_only: [] }),
  },
  {
    type: "provenance",
    label: "Provenance",
    category: "Action control",
    description: "Find tool arguments sourced from untrusted results.",
    defaultConfig: () => ({ checkpoint: "tool_call" }),
  },
];

export const nodeCatalogByType = Object.fromEntries(
  nodeCatalog.map((item) => [item.type, item]),
) as Record<GuardrailNodeType, NodeCatalogItem>;

export function nodeSummary(node: GuardrailNode): string {
  switch (node.type) {
    case "extract":
    case "taint":
      return checkpointName(node.config.checkpoint);
    case "regex":
      return stringConfig(node, "pattern") || "Pattern not set";
    case "length":
      return `≤ ${numberConfig(node, "max_chars") ?? "?"} chars`;
    case "transform":
      return stringConfig(node, "op") || "Operation not set";
    case "verdict":
      return `${stringConfig(node, "action") || "action"} · ${
        stringConfig(node, "decision") || "decision"
      }`;
    case "all":
      return "Every input must match";
    case "side_effect": {
      const readOnly = node.config.read_only;
      const count = Array.isArray(readOnly) ? readOnly.length : 0;
      return `${count} read-only tool${count === 1 ? "" : "s"}`;
    }
    case "provenance":
      return `Minimum ${numberConfig(node, "min_length") ?? 8} chars`;
  }
}

export function incomingRange(type: GuardrailNodeType): {
  min: number;
  max: number | null;
} {
  switch (type) {
    case "extract":
    case "taint":
    case "side_effect":
    case "provenance":
      return { min: 0, max: 0 };
    case "regex":
    case "length":
    case "transform":
      return { min: 1, max: 1 };
    case "all":
      return { min: 2, max: null };
    case "verdict":
      return { min: 1, max: null };
  }
}

export function canEmit(type: GuardrailNodeType): boolean {
  return type !== "verdict";
}

function checkpointName(value: unknown): string {
  return typeof value === "string"
    ? value.replaceAll("_", " ")
    : "Checkpoint not set";
}

function stringConfig(node: GuardrailNode, key: string): string | null {
  return typeof node.config[key] === "string" ? node.config[key] : null;
}

function numberConfig(node: GuardrailNode, key: string): number | null {
  return typeof node.config[key] === "number" ? node.config[key] : null;
}
