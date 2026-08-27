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
  }
> = {
  input: {
    index: "①",
    label: "입력",
    shortLabel: "사용자 메시지",
    description: "사용자 의도를 검사합니다",
  },
  tool_result: {
    index: "②",
    label: "툴 결과",
    shortLabel: "신뢰하지 않는 데이터",
    description: "외부에서 들어온 데이터를 검사합니다",
  },
  tool_call: {
    index: "④",
    label: "툴 호출",
    shortLabel: "에이전트 액션",
    description: "외부에 영향을 주는 액션을 검사합니다",
  },
  output: {
    index: "③",
    label: "출력",
    shortLabel: "모델 응답",
    description: "사용자에게 돌아갈 응답을 검사합니다",
  },
};

export type NodeCatalogItem = {
  type: GuardrailNodeType;
  label: string;
  category: NodeCatalogRole;
  description: string;
  defaultConfig: (checkpoint: Checkpoint) => Record<string, unknown>;
};

export type NodeCatalogRole = "Extract" | "Transform" | "Check" | "Verdict";

export type NodeCatalogGroup = {
  role: NodeCatalogRole;
  description: string;
  items: NodeCatalogItem[];
};

const catalogRoles: ReadonlyArray<
  Pick<NodeCatalogGroup, "role" | "description">
> = [
  { role: "Extract", description: "무엇을 볼지" },
  { role: "Transform", description: "입력을 다듬는다" },
  { role: "Check", description: "조건을 확인한다" },
  { role: "Verdict", description: "결론과 조합을 정한다" },
];

export const nodeCatalog: NodeCatalogItem[] = [
  {
    type: "extract",
    label: "텍스트 추출",
    category: "Extract",
    description: "이 검사 지점의 텍스트를 읽습니다.",
    defaultConfig: (checkpoint) => ({ checkpoint }),
  },
  {
    type: "regex",
    label: "정규식",
    category: "Check",
    description: "RE2 정책 패턴과 일치하는지 검사합니다.",
    defaultConfig: () => ({ pattern: "" }),
  },
  {
    type: "transform",
    label: "텍스트 변환",
    category: "Transform",
    description: "다른 검사 전에 텍스트를 정규화합니다.",
    defaultConfig: () => ({ op: "lower" }),
  },
  {
    type: "taint",
    label: "오염 추적",
    category: "Check",
    description: "툴 데이터가 대화에 들어왔는지 추적합니다.",
    defaultConfig: (checkpoint) => ({ checkpoint }),
  },
  {
    type: "side_effect",
    label: "부작용 툴",
    category: "Check",
    description: "읽기 전용 목록에 없는 모든 툴을 위험한 액션으로 처리합니다.",
    defaultConfig: () => ({ checkpoint: "tool_call", read_only: [] }),
  },
  {
    type: "provenance",
    label: "인수 출처",
    category: "Check",
    description: "신뢰하지 않는 툴 결과에서 가져온 호출 인수를 찾습니다.",
    defaultConfig: () => ({ checkpoint: "tool_call" }),
  },
  {
    type: "model",
    label: "MODEL 검사",
    category: "Check",
    description: "자연어 정책 질의로 모델 판정을 요청합니다.",
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
    description: "입력이 일치하면 차단, 마스킹 또는 허용으로 판정합니다.",
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
  input: ["extract", "transform", "regex", "model", "verdict"],
  tool_result: [
    "extract",
    "transform",
    "regex",
    "taint",
    "model",
    "verdict",
  ],
  tool_call: ["taint", "side_effect", "provenance", "model", "verdict"],
  output: ["extract", "transform", "regex", "model", "verdict"],
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
    case "transform":
      return transformName(stringConfig(node, "op"));
    case "verdict":
      return `${actionName(stringConfig(node, "action"))} · ${combineName(
        stringConfig(node, "combine"),
      )}`;
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

function stringConfig(node: GuardrailNode, key: string): string | null {
  return typeof node.config[key] === "string" ? node.config[key] : null;
}

function numberConfig(node: GuardrailNode, key: string): number | null {
  return typeof node.config[key] === "number" ? node.config[key] : null;
}
