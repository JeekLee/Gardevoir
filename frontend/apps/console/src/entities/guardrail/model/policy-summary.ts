import {
  checkpoints,
  guardrailActions,
  type Checkpoint,
  type GuardrailAction,
  type GuardrailGraph,
  type GuardrailSummary,
} from "./guardrail";

const checkpointCopy: Record<
  Checkpoint,
  { label: string; index: "①" | "②" | "④" | "③" }
> = {
  input: { label: "입력", index: "①" },
  tool_result: { label: "툴 결과", index: "②" },
  tool_call: { label: "툴 호출", index: "④" },
  output: { label: "출력", index: "③" },
};

const actionCopy: Record<GuardrailAction, string> = {
  block: "차단",
  mask: "마스킹",
  allow: "허용",
};

export function describeGuardrailGraph(graph: GuardrailGraph): string {
  if (graph.nodes.length === 0) return "아직 정책 규칙이 없습니다.";

  const nodeTypes = new Set(graph.nodes.map((node) => node.type));
  const { coveredCheckpoints, actions } = projectGraph(graph);
  const action = actionPhrase(actions);

  if (
    nodeTypes.has("tool_extract") &&
    graph.nodes.some(
      (node) =>
        node.type === "extract" &&
        node.config.from === "tool_result" &&
        node.config.at === "tool_call",
    )
  ) {
    return `오염된 대화에서 부작용 툴 호출을 ${action}합니다 (② → ④).`;
  }
  if (nodeTypes.has("regex") && coveredCheckpoints.includes("output")) {
    return `출력에서 패턴이 매칭되면 ${action}합니다 (③).`;
  }
  return genericDescription(coveredCheckpoints, actions);
}

export function describeGuardrailSummary(
  summary: Pick<
    GuardrailSummary,
    "checkpoints" | "actions" | "checkCount" | "verdictCount"
  >,
): string {
  if (
    summary.checkpoints.length === 0 &&
    summary.actions.length === 0 &&
    summary.checkCount === 0 &&
    summary.verdictCount === 0
  ) {
    return "빈 초안";
  }

  const scope = summary.checkpoints
    .map((checkpoint) => checkpointCopy[checkpoint].label)
    .join("·");
  const indices = checkpointIndices(summary.checkpoints);
  const outcome = actionPhrase(summary.actions);

  if (scope && summary.actions.length > 0) {
    return `${scope}을 검사해 ${outcome}합니다${indices}.`;
  }
  if (scope) return `${scope}에서 정책 조건을 검사합니다${indices}.`;
  if (summary.actions.length > 0) return `정책 조건이 맞으면 ${outcome}합니다.`;
  return `체크 ${summary.checkCount}개 · verdict ${summary.verdictCount}개 정책입니다.`;
}

function projectGraph(graph: GuardrailGraph): {
  coveredCheckpoints: Checkpoint[];
  actions: GuardrailAction[];
} {
  const covered = new Set<Checkpoint>();
  const actions = new Set<GuardrailAction>();

  for (const node of graph.nodes) {
    if (node.type === "tool_extract") {
      covered.add("tool_call");
    } else if (isCheckpoint(node.config.at)) {
      covered.add(node.config.at);
    } else if (isCheckpoint(node.config.checkpoint)) {
      covered.add(node.config.checkpoint);
    }
    if (node.type === "verdict" && isAction(node.config.action)) {
      actions.add(node.config.action);
    }
  }

  return {
    coveredCheckpoints: checkpoints.filter((checkpoint) => covered.has(checkpoint)),
    actions: guardrailActions.filter((action) => actions.has(action)),
  };
}

function genericDescription(
  coveredCheckpoints: Checkpoint[],
  actions: GuardrailAction[],
): string {
  const scope = coveredCheckpoints
    .map((checkpoint) => checkpointCopy[checkpoint].label)
    .join("·");
  const indices = checkpointIndices(coveredCheckpoints);
  if (scope && actions.length > 0) {
    return `${scope}에서 조건이 맞으면 ${actionPhrase(actions)}합니다${indices}.`;
  }
  if (scope) return `${scope}에서 정책 조건을 검사합니다${indices}.`;
  if (actions.length > 0) {
    return `정책 조건이 맞으면 ${actionPhrase(actions)}합니다.`;
  }
  return "정책 그래프의 연결과 설정을 확인하세요.";
}

function checkpointIndices(values: Checkpoint[]): string {
  if (values.length === 0) return "";
  return ` (${values.map((checkpoint) => checkpointCopy[checkpoint].index).join(" · ")})`;
}

function actionPhrase(actions: GuardrailAction[]): string {
  if (actions.length === 0) return "검사";
  if (actions.length === 1) return actionCopy[actions[0]];
  const labels = actions.map((action) => actionCopy[action]);
  return `${labels.slice(0, -1).join("·")} 또는 ${labels.at(-1)}`;
}

function isCheckpoint(value: unknown): value is Checkpoint {
  return checkpoints.some((checkpoint) => checkpoint === value);
}

function isAction(value: unknown): value is GuardrailAction {
  return guardrailActions.some((action) => action === value);
}
