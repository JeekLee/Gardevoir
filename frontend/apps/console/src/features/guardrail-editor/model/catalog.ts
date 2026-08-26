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
  category: "소스" | "검사" | "논리" | "결과" | "액션 통제";
  description: string;
  defaultConfig: (checkpoint: Checkpoint) => Record<string, unknown>;
};

export const nodeCatalog: NodeCatalogItem[] = [
  {
    type: "extract",
    label: "텍스트 추출",
    category: "소스",
    description: "이 검사 지점의 텍스트를 읽습니다.",
    defaultConfig: (checkpoint) => ({ checkpoint }),
  },
  {
    type: "regex",
    label: "정규식",
    category: "검사",
    description: "RE2 정책 패턴과 일치하는지 검사합니다.",
    defaultConfig: () => ({ pattern: "" }),
  },
  {
    type: "length",
    label: "길이",
    category: "검사",
    description: "최대 글자 수를 검사합니다.",
    defaultConfig: () => ({ max_chars: 1_000 }),
  },
  {
    type: "transform",
    label: "텍스트 변환",
    category: "검사",
    description: "다른 검사 전에 텍스트를 정규화합니다.",
    defaultConfig: () => ({ op: "lower" }),
  },
  {
    type: "verdict",
    label: "판정",
    category: "결과",
    description: "입력이 일치하면 차단, 마스킹 또는 허용으로 판정합니다.",
    defaultConfig: () => ({
      action: "block",
      code: "policy-match",
      decision: "conclusive",
    }),
  },
  {
    type: "taint",
    label: "오염 추적",
    category: "액션 통제",
    description: "툴 데이터가 대화에 들어왔는지 추적합니다.",
    defaultConfig: (checkpoint) => ({ checkpoint }),
  },
  {
    type: "all",
    label: "모두 일치",
    category: "논리",
    description: "연결된 모든 검사가 일치해야 통과합니다.",
    defaultConfig: () => ({}),
  },
  {
    type: "side_effect",
    label: "부작용 툴",
    category: "액션 통제",
    description: "읽기 전용 목록에 없는 모든 툴을 위험한 액션으로 처리합니다.",
    defaultConfig: () => ({ checkpoint: "tool_call", read_only: [] }),
  },
  {
    type: "provenance",
    label: "인수 출처",
    category: "액션 통제",
    description: "신뢰하지 않는 툴 결과에서 가져온 호출 인수를 찾습니다.",
    defaultConfig: () => ({ checkpoint: "tool_call" }),
  },
];

export const nodeCatalogByType = Object.fromEntries(
  nodeCatalog.map((item) => [item.type, item]),
) as Record<GuardrailNodeType, NodeCatalogItem>;

const catalogTypesByCheckpoint: Record<
  Checkpoint,
  readonly GuardrailNodeType[]
> = {
  input: ["extract", "regex", "length", "transform", "verdict"],
  tool_result: [
    "extract",
    "regex",
    "length",
    "transform",
    "verdict",
    "taint",
  ],
  tool_call: ["taint", "side_effect", "provenance", "all", "verdict"],
  output: ["extract", "regex", "length", "transform", "verdict"],
};

export function catalogForCheckpoint(
  checkpoint: Checkpoint,
): NodeCatalogItem[] {
  return catalogTypesByCheckpoint[checkpoint].map(
    (type) => nodeCatalogByType[type],
  );
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
    case "length":
      return `최대 ${numberConfig(node, "max_chars") ?? "?"}자`;
    case "transform":
      return transformName(stringConfig(node, "op"));
    case "verdict":
      return `${actionName(stringConfig(node, "action"))} · ${decisionName(
        stringConfig(node, "decision"),
      )}`;
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

function decisionName(value: string | null): string {
  if (value === "conclusive") return "결론형";
  if (value === "hint") return "힌트형";
  if (value === "model_only") return "모델형";
  return "역할 미설정";
}

function stringConfig(node: GuardrailNode, key: string): string | null {
  return typeof node.config[key] === "string" ? node.config[key] : null;
}

function numberConfig(node: GuardrailNode, key: string): number | null {
  return typeof node.config[key] === "number" ? node.config[key] : null;
}
