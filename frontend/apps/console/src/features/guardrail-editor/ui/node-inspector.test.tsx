import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import type { GuardrailGraph } from "@/src/entities/guardrail";

import { toEditorGraph } from "../model/graph-mapper";
import { NodeInspector } from "./node-inspector";

it("기존 MODEL MASK 값은 표시하되 마스킹 선택은 비활성화한다", () => {
  const wire: GuardrailGraph = {
    nodes: [
      {
        id: "extract",
        type: "extract",
        config: { checkpoint: "input" },
      },
      {
        id: "model",
        type: "model",
        config: {
          checkpoint: "input",
          policy: "민감정보인가?",
          strictness: "strict",
        },
      },
      { id: "verdict", type: "verdict", config: { action: "mask" } },
    ],
    edges: [
      { src: "extract", dst: "model" },
      { src: "model", dst: "verdict" },
    ],
  };
  const graph = toEditorGraph(wire);
  const selectedNode = graph.nodes.find((node) => node.id === "verdict") ?? null;
  const html = renderToStaticMarkup(
    <NodeInspector
      graph={graph}
      selectedNode={selectedNode}
      readOnly={false}
      onSelect={vi.fn()}
      onConfigChange={vi.fn()}
      onDelete={vi.fn()}
      onConnect={vi.fn()}
      onRemoveEdge={vi.fn()}
    />,
  );

  expect(html).toContain('<option value="mask" disabled="" selected="">마스킹</option>');
  expect(html).toContain("모델 판정은 위치를 제공하지 않아 마스킹할 수 없습니다.");
});
