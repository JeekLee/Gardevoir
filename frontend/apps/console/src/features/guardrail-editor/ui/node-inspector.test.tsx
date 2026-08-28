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

it("옛 extract checkpoint를 새 from·at 선택으로 표시한다", () => {
  const wire: GuardrailGraph = {
    nodes: [
      {
        id: "legacy-extract",
        type: "extract",
        config: { checkpoint: "input" },
      },
    ],
    edges: [],
  };
  const graph = toEditorGraph(wire);
  const html = renderToStaticMarkup(
    <NodeInspector
      graph={graph}
      selectedNode={graph.nodes[0]}
      readOnly={false}
      onSelect={vi.fn()}
      onConfigChange={vi.fn()}
      onDelete={vi.fn()}
      onConnect={vi.fn()}
      onRemoveEdge={vi.fn()}
    />,
  );

  expect(html).toContain('<option value="user_text" selected="">');
  expect(html).toContain('<option value="input" selected="">');
});

it("tool_extract의 안전한 exclude 기본값과 인수 경로를 표시한다", () => {
  const wire: GuardrailGraph = {
    nodes: [
      {
        id: "tool-field",
        type: "tool_extract",
        config: { tools: { exclude: ["read_file"] }, field: "to" },
      },
    ],
    edges: [],
  };
  const graph = toEditorGraph(wire);
  const html = renderToStaticMarkup(
    <NodeInspector
      graph={graph}
      selectedNode={graph.nodes[0]}
      readOnly={false}
      onSelect={vi.fn()}
      onConfigChange={vi.fn()}
      onDelete={vi.fn()}
      onConnect={vi.fn()}
      onRemoveEdge={vi.fn()}
    />,
  );

  expect(html).toContain("기본값 · 목록에 없는 툴이 검사 대상입니다.");
  expect(html).toContain("read_file");
  expect(html).toContain('placeholder="to · payload.meta.id · cc[*]"');
});
