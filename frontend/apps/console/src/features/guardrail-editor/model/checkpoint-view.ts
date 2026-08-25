import {
  checkpoints,
  guardrailActions,
  type Checkpoint,
  type GuardrailAction,
} from "@/src/entities/guardrail";

import type { EditorGraph } from "./graph-mapper";

export const editorTabs = ["overview", ...checkpoints] as const;

export type EditorTab = (typeof editorTabs)[number];

export function editorTabAfterKey(
  activeTab: EditorTab,
  key: string,
): EditorTab | null {
  const current = editorTabs.indexOf(activeTab);
  let next: number;
  if (key === "ArrowRight") next = (current + 1) % editorTabs.length;
  else if (key === "ArrowLeft") {
    next = (current - 1 + editorTabs.length) % editorTabs.length;
  } else if (key === "Home") next = 0;
  else if (key === "End") next = editorTabs.length - 1;
  else return null;

  return editorTabs[next];
}

export type CheckpointGraphSummary = {
  checkpoint: Checkpoint;
  nodeCount: number;
  verdictCount: number;
  actions: GuardrailAction[];
};

export function graphForCheckpoint(
  graph: EditorGraph,
  checkpoint: Checkpoint,
): EditorGraph {
  const nodes = graph.nodes.filter(
    (node) => node.data.checkpoint === checkpoint,
  );
  const nodeIds = new Set(nodes.map((node) => node.id));
  return {
    nodes,
    edges: graph.edges.filter(
      (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
    ),
  };
}

export function summarizeCheckpointGraphs(
  graph: EditorGraph,
): CheckpointGraphSummary[] {
  return checkpoints.map((checkpoint) => {
    const nodes = graph.nodes.filter(
      (node) => node.data.checkpoint === checkpoint,
    );
    const verdicts = nodes.filter(
      (node) => node.data.domainNode.type === "verdict",
    );
    const actionSet = new Set(
      verdicts
        .map((node) => node.data.domainNode.config.action)
        .filter(isGuardrailAction),
    );
    return {
      checkpoint,
      nodeCount: nodes.length,
      verdictCount: verdicts.length,
      actions: guardrailActions.filter((action) => actionSet.has(action)),
    };
  });
}

export function checkpointForNode(
  graph: EditorGraph,
  nodeId: string,
): Checkpoint | null {
  return (
    graph.nodes.find((node) => node.id === nodeId)?.data.checkpoint ?? null
  );
}

function isGuardrailAction(value: unknown): value is GuardrailAction {
  return guardrailActions.some((action) => action === value);
}
