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

export type NodeCatalogRole = "Extract" | "Check" | "Verdict";

export type NodeCatalogGroup = {
  role: NodeCatalogRole;
  items: NodeCatalogItem[];
};

const catalogRoles: ReadonlyArray<Pick<NodeCatalogGroup, "role">> = [
  { role: "Extract" },
  { role: "Check" },
  { role: "Verdict" },
];

export const nodeCatalog: NodeCatalogItem[] = [
  {
    type: "extract",
    label: "텍스트 추출",
    category: "Extract",
    defaultConfig: (checkpoint) => ({ checkpoint }),
  },
  {
    type: "regex",
    label: "정규식",
    category: "Check",
    defaultConfig: () => ({ pattern: "" }),
  },
  {
    type: "length",
    label: "길이",
    category: "Check",
    defaultConfig: () => ({ max_chars: 1_000 }),
  },
  {
    type: "transform",
    label: "텍스트 변환",
    category: "Check",
    defaultConfig: () => ({ op: "lower" }),
  },
  {
    type: "taint",
    label: "오염 추적",
    category: "Check",
    defaultConfig: (checkpoint) => ({ checkpoint }),
  },
  {
    type: "all",
    label: "모두 일치",
    category: "Check",
    defaultConfig: () => ({}),
  },
  {
    type: "side_effect",
    label: "부작용 툴",
    category: "Check",
    defaultConfig: () => ({ checkpoint: "tool_call", read_only: [] }),
  },
  {
    type: "provenance",
    label: "인수 출처",
    category: "Check",
    defaultConfig: () => ({ checkpoint: "tool_call" }),
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
    defaultConfig: () => ({ action: "block" }),
  },
];

export const nodeCatalogByType = Object.fromEntries(
  nodeCatalog.map((item) => [item.type, item]),
) as Record<GuardrailNodeType, NodeCatalogItem>;

const catalogTypesByCheckpoint: Record<
  Checkpoint,
  readonly GuardrailNodeType[]
> = {
  input: [
    "extract",
    "regex",
    "length",
    "transform",
    "model",
    "all",
    "verdict",
  ],
  tool_result: [
    "extract",
    "regex",
    "length",
    "transform",
    "taint",
    "model",
    "all",
    "verdict",
  ],
  tool_call: [
    "taint",
    "side_effect",
    "provenance",
    "model",
    "all",
    "verdict",
  ],
  output: [
    "extract",
    "regex",
    "length",
    "transform",
    "model",
    "all",
    "verdict",
  ],
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
    case "extract":
    case "taint":
      return checkpointName(node.config.checkpoint);
    case "regex":
      return stringConfig(node, "pattern") || "패턴 미설정";
    case "model": {
      const policy = stringConfig(node, "policy")?.trim();
      return policy
        ? `${strictnessName(stringConfig(node, "strictness"))} · ${policy}`
        : "정책 미설정";
    }
    case "length":
      return `최대 ${numberConfig(node, "max_chars") ?? "?"}자`;
    case "transform":
      return transformName(stringConfig(node, "op"));
    case "verdict":
      return actionName(stringConfig(node, "action"));
    case "all":
      return "모든 입력이 일치해야 함";
    case "side_effect": {
      const readOnly = node.config.read_only;
      const count = Array.isArray(readOnly) ? readOnly.length : 0;
      return `읽기 전용 툴 ${count}개`;
    }
    case "provenance":
      return `최소 ${numberConfig(node, "min_length") ?? 8}자`;
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
    case "model":
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

function strictnessName(value: string | null): string {
  if (value === "balanced") return "균형";
  if (value === "lenient") return "관대";
  return "엄격";
}

function stringConfig(node: GuardrailNode, key: string): string | null {
  return typeof node.config[key] === "string" ? node.config[key] : null;
}

function numberConfig(node: GuardrailNode, key: string): number | null {
  return typeof node.config[key] === "number" ? node.config[key] : null;
}
