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
  }
> = {
  input: {
    index: "①",
    label: "입력",
    shortLabel: "사용자 메시지",
  },
  tool_result: {
    index: "②",
    label: "툴 결과",
    shortLabel: "신뢰하지 않는 데이터",
  },
  tool_call: {
    index: "④",
    label: "툴 호출",
    shortLabel: "에이전트 액션",
  },
  output: {
    index: "③",
    label: "출력",
    shortLabel: "모델 응답",
  },
};

export type NodeCatalogItem = {
  type: GuardrailNodeType;
  label: string;
  category: NodeCatalogRole;
  defaultConfig: (checkpoint: Checkpoint) => Record<string, unknown>;
};

export type NodeCatalogRole = "Extract" | "Transform" | "Check" | "Verdict";

export type NodeCatalogGroup = {
  role: NodeCatalogRole;
  items: NodeCatalogItem[];
};

const catalogRoles: ReadonlyArray<Pick<NodeCatalogGroup, "role">> = [
  { role: "Extract" },
  { role: "Transform" },
  { role: "Check" },
  { role: "Verdict" },
];

export const nodeCatalog: NodeCatalogItem[] = [
  {
    type: "extract",
    label: "텍스트 추출",
    category: "Extract",
    defaultConfig: (checkpoint) => ({
      from: defaultExtractSource(checkpoint),
      at: checkpoint,
    }),
  },
  {
    type: "tool_extract",
    label: "툴 필드 추출",
    category: "Extract",
    defaultConfig: () => ({ tools: { exclude: [] }, field: "name" }),
  },
  {
    type: "transform",
    label: "텍스트 변환",
    category: "Transform",
    defaultConfig: () => ({ op: "lower" }),
  },
  {
    type: "regex",
    label: "정규식",
    category: "Check",
    defaultConfig: () => ({ pattern: "" }),
  },
  {
    type: "not",
    label: "NOT",
    category: "Check",
    defaultConfig: () => ({}),
  },
  {
    type: "model",
    label: "MODEL 검사",
    category: "Check",
    defaultConfig: (checkpoint) => ({
      policy: "",
      strictness: "strict",
      checkpoint,
    }),
  },
  {
    type: "verdict",
    label: "판정",
    category: "Verdict",
    defaultConfig: () => ({ action: "block", combine: "any" }),
  },
];

export const nodeCatalogByType = Object.fromEntries(
  nodeCatalog.map((item) => [item.type, item]),
) as Record<GuardrailNodeType, NodeCatalogItem>;

const catalogTypesByCheckpoint: Record<
  Checkpoint,
  readonly GuardrailNodeType[]
> = {
  input: ["extract", "transform", "regex", "model", "not", "verdict"],
  tool_result: ["extract", "transform", "regex", "model", "not", "verdict"],
  tool_call: [
    "extract",
    "tool_extract",
    "transform",
    "regex",
    "model",
    "not",
    "verdict",
  ],
  output: ["extract", "transform", "regex", "model", "not", "verdict"],
};

export function catalogForCheckpoint(
  checkpoint: Checkpoint,
): NodeCatalogItem[] {
  return catalogTypesByCheckpoint[checkpoint].map(
    (type) => nodeCatalogByType[type],
  );
}

export function catalogGroupsForCheckpoint(
  checkpoint: Checkpoint,
): NodeCatalogGroup[] {
  const catalog = catalogForCheckpoint(checkpoint);
  return catalogRoles.flatMap((group) => {
    const items = catalog.filter((item) => item.category === group.role);
    return items.length > 0 ? [{ ...group, items }] : [];
  });
}

export function createCatalogNode(
  type: GuardrailNodeType,
  checkpoint: Checkpoint,
  id: string,
): GuardrailNode {
  if (!catalogTypesByCheckpoint[checkpoint].includes(type)) {
    throw new Error(`${type} is not available at ${checkpoint}`);
  }
  return {
    id,
    type,
    config: nodeCatalogByType[type].defaultConfig(checkpoint),
  };
}

export function nodeSummary(node: GuardrailNode): string {
  switch (node.type) {
    case "extract": {
      const at = node.config.at ?? node.config.checkpoint;
      const source = node.config.from ?? legacyExtractSource(node.config.checkpoint);
      return `${extractSourceName(source)} → ${checkpointName(at)}`;
    }
    case "tool_extract": {
      const selector = toolSelector(node.config.tools);
      return `${selector.label} ${selector.names.length}개 · ${stringConfig(node, "field") || "필드 미설정"}`;
    }
    case "regex":
      return stringConfig(node, "pattern") || "패턴 미설정";
    case "model": {
      const policy = stringConfig(node, "policy")?.trim();
      return policy
        ? `${strictnessName(stringConfig(node, "strictness"))} · ${policy}`
        : "정책 미설정";
    }
    case "transform":
      return transformName(stringConfig(node, "op"));
    case "verdict":
      return `${actionName(stringConfig(node, "action"))} · ${combineName(
        stringConfig(node, "combine"),
      )}`;
    case "not":
      return "입력 부정";
  }
}

export function incomingRange(type: GuardrailNodeType): {
  min: number;
  max: number | null;
} {
  switch (type) {
    case "extract":
    case "tool_extract":
      return { min: 0, max: 0 };
    case "regex":
    case "model":
    case "not":
    case "transform":
      return { min: 1, max: 1 };
    case "verdict":
      return { min: 1, max: null };
  }
}

export function canEmit(type: GuardrailNodeType): boolean {
  return type !== "verdict";
}

function checkpointName(value: unknown): string {
  if (value === "input") return "입력";
  if (value === "tool_result") return "툴 결과";
  if (value === "tool_call") return "툴 호출";
  if (value === "output") return "출력";
  return "검사 지점 미설정";
}

function transformName(value: string | null): string {
  if (value === "lower") return "소문자 변환";
  if (value === "strip") return "앞뒤 공백 제거";
  return "변환 방식 미설정";
}

function actionName(value: string | null): string {
  if (value === "block") return "차단";
  if (value === "mask") return "마스킹";
  if (value === "allow") return "허용";
  return "판정 미설정";
}

function combineName(value: string | null): string {
  return value === "all" ? "모두 충족 (AND)" : "하나라도 충족 (OR)";
}

function strictnessName(value: string | null): string {
  if (value === "balanced") return "균형";
  if (value === "lenient") return "관대";
  return "엄격";
}

function defaultExtractSource(checkpoint: Checkpoint): string {
  if (checkpoint === "input") return "user_text";
  if (checkpoint === "output") return "output_text";
  return "tool_result";
}

function legacyExtractSource(value: unknown): unknown {
  if (value === "input") return "user_text";
  if (value === "tool_result") return "tool_result";
  if (value === "output") return "output_text";
  return null;
}

function extractSourceName(value: unknown): string {
  if (value === "user_text") return "사용자 텍스트";
  if (value === "tool_result") return "툴 결과";
  if (value === "trusted_text") return "신뢰 텍스트";
  if (value === "output_text") return "출력 텍스트";
  return "추출 대상 미설정";
}

function toolSelector(value: unknown): {
  label: "제외" | "포함";
  names: string[];
} {
  if (isRecord(value) && Array.isArray(value.include)) {
    return {
      label: "포함",
      names: value.include.filter((name): name is string => typeof name === "string"),
    };
  }
  return {
    label: "제외",
    names:
      isRecord(value) && Array.isArray(value.exclude)
        ? value.exclude.filter((name): name is string => typeof name === "string")
        : [],
  };
}

function stringConfig(node: GuardrailNode, key: string): string | null {
  return typeof node.config[key] === "string" ? node.config[key] : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
