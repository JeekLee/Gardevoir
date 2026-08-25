import { describe, expect, it } from "vitest";

import type { GuardrailGraph } from "@/src/entities/guardrail";

import { catalogForCheckpoint, createCatalogNode } from "./catalog";
import {
  checkpointForNode,
  editorTabAfterKey,
  graphForCheckpoint,
  summarizeCheckpointGraphs,
} from "./checkpoint-view";
import { toEditorGraph } from "./graph-mapper";

const graph: GuardrailGraph = {
  nodes: [
    { id: "input", type: "extract", config: { checkpoint: "input" } },
    { id: "input-check", type: "regex", config: { pattern: "secret" } },
    {
      id: "input-verdict",
      type: "verdict",
      config: { action: "block", decision: "conclusive", code: "input" },
    },
    { id: "output", type: "extract", config: { checkpoint: "output" } },
    {
      id: "output-verdict",
      type: "verdict",
      config: { action: "mask", decision: "conclusive", code: "output" },
    },
  ],
  edges: [
    { src: "input", dst: "input-check" },
    { src: "input-check", dst: "input-verdict" },
    { src: "output", dst: "output-verdict" },
  ],
};

describe("checkpoint editor view", () => {
  it("전체 그래프의 선언 순서를 유지하며 한 체크포인트의 노드와 엣지만 고른다", () => {
    const editor = toEditorGraph(graph);
    const input = graphForCheckpoint(editor, "input");

    expect(input.nodes.map((node) => node.id)).toEqual([
      "input",
      "input-check",
      "input-verdict",
    ]);
    expect(input.edges.map((edge) => [edge.source, edge.target])).toEqual([
      ["input", "input-check"],
      ["input-check", "input-verdict"],
    ]);
    expect(editor.nodes).toHaveLength(5);
    expect(checkpointForNode(editor, "output-verdict")).toBe("output");
  });

  it("체크포인트별 노드·verdict·결과를 전체 그래프에서 집계한다", () => {
    const summaries = summarizeCheckpointGraphs(toEditorGraph(graph));

    expect(summaries).toEqual([
      {
        checkpoint: "input",
        nodeCount: 3,
        verdictCount: 1,
        actions: ["block"],
      },
      {
        checkpoint: "tool_result",
        nodeCount: 0,
        verdictCount: 0,
        actions: [],
      },
      {
        checkpoint: "tool_call",
        nodeCount: 0,
        verdictCount: 0,
        actions: [],
      },
      {
        checkpoint: "output",
        nodeCount: 2,
        verdictCount: 1,
        actions: ["mask"],
      },
    ]);
  });

  it("체크포인트에 유효한 카탈로그만 노출하고 소스 checkpoint를 탭에 고정한다", () => {
    expect(catalogForCheckpoint("input").map((item) => item.type)).toEqual([
      "extract",
      "regex",
      "length",
      "transform",
      "verdict",
    ]);
    expect(catalogForCheckpoint("tool_result").map((item) => item.type)).toEqual([
      "extract",
      "regex",
      "length",
      "transform",
      "verdict",
      "taint",
    ]);
    expect(catalogForCheckpoint("tool_call").map((item) => item.type)).toEqual([
      "taint",
      "side_effect",
      "provenance",
      "all",
      "verdict",
    ]);
    expect(createCatalogNode("extract", "output", "new-source")).toEqual({
      id: "new-source",
      type: "extract",
      config: { checkpoint: "output" },
    });
    expect(() => createCatalogNode("regex", "tool_call", "invalid")).toThrow(
      "regex is not available at tool_call",
    );
  });

  it("방향키와 Home·End 키로 탭 포커스 순서를 순환한다", () => {
    expect(editorTabAfterKey("overview", "ArrowLeft")).toBe("output");
    expect(editorTabAfterKey("output", "ArrowRight")).toBe("overview");
    expect(editorTabAfterKey("tool_result", "Home")).toBe("overview");
    expect(editorTabAfterKey("tool_result", "End")).toBe("output");
    expect(editorTabAfterKey("input", "Enter")).toBeNull();
  });
});
