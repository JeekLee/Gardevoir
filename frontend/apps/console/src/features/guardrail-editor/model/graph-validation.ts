import type { GuardrailNode } from "@/src/entities/guardrail";

import type { EditorGraph } from "./graph-mapper";

export type NodeValidationError = {
  nodeId: string;
  message: string;
};

export function validateEditorGraph(
  graph: EditorGraph,
): NodeValidationError[] {
  return graph.nodes.flatMap((node) => validateNode(node.data.domainNode));
}

function validateNode(node: GuardrailNode): NodeValidationError[] {
  if (
    node.type === "model" &&
    (typeof node.config.policy !== "string" || !node.config.policy.trim())
  ) {
    return [
      {
        nodeId: node.id,
        message: "MODEL 검사의 자연어 정책 질의를 입력하세요.",
      },
    ];
  }
  return [];
}
