import { describe, expect, it } from "vitest";

import type { GuardrailGraph } from "@/src/entities/guardrail";

import {
  mergeCanonicalGraph,
  toEditorGraph,
  toGuardrailGraph,
} from "./graph-mapper";

const graph: GuardrailGraph = {
  nodes: [
    {
      id: "source",
      type: "extract",
      config: { checkpoint: "tool_result", futureField: { keep: true } },
    },
    { id: "match", type: "regex", config: { pattern: "secret" } },
    {
      id: "model-check",
      type: "model",
      config: {
        policy: "이 텍스트가 비밀 정보를 노출하는가?",
        strictness: "balanced",
        checkpoint: "tool_result",
      },
    },
    {
      id: "decision",
      type: "verdict",
      config: { action: "block", code: "secret-found" },
    },
  ],
  edges: [
    { src: "source", dst: "match" },
    { src: "source", dst: "model-check" },
    { src: "match", dst: "decision" },
    { src: "model-check", dst: "decision" },
  ],
};

describe("guardrail graph mapper", () => {
  it("preserves domain identity, config, and declaration order through the editor", () => {
    const roundTrip = toGuardrailGraph(toEditorGraph(graph));

    expect(roundTrip).toEqual(graph);
    expect(roundTrip.nodes.map((node) => node.id)).toEqual([
      "source",
      "match",
      "model-check",
      "decision",
    ]);
    expect(roundTrip.nodes[2].config).toEqual({
      policy: "이 텍스트가 비밀 정보를 노출하는가?",
      strictness: "balanced",
      checkpoint: "tool_result",
    });
  });

  it("maps wire edge endpoints without sending editor-only state", () => {
    const editor = toEditorGraph(graph);
    editor.nodes[0] = {
      ...editor.nodes[0],
      selected: true,
      position: { x: 777, y: 888 },
      data: { ...editor.nodes[0].data, validationMessage: "invalid" },
    };

    const wire = toGuardrailGraph(editor);

    expect(wire.edges).toEqual(graph.edges);
    expect(wire.nodes[0]).not.toHaveProperty("position");
    expect(wire.nodes[0]).not.toHaveProperty("selected");
    expect(wire.nodes[0].config).toEqual(graph.nodes[0].config);
  });

  it("keeps working positions when a saved draft becomes canonical", () => {
    const editor = toEditorGraph(graph);
    editor.nodes[1] = { ...editor.nodes[1], position: { x: 402, y: 306 } };

    const merged = mergeCanonicalGraph(graph, editor);

    expect(merged.nodes[1].position).toEqual({ x: 402, y: 306 });
  });

  it("drops a legacy verdict decision without losing other config", () => {
    const legacy: GuardrailGraph = {
      ...graph,
      nodes: graph.nodes.map((node) =>
        node.type === "verdict"
          ? {
              ...node,
              config: { ...node.config, decision: "hint", futureField: true },
            }
          : node,
      ),
    };

    const verdict = toGuardrailGraph(toEditorGraph(legacy)).nodes.at(-1);

    expect(verdict?.config).toEqual({
      action: "block",
      code: "secret-found",
      futureField: true,
    });
  });

  it("새 from·at 문법과 tool_extract를 tool_call 탭에 배치한다", () => {
    const redesigned: GuardrailGraph = {
      nodes: [
        {
          id: "tool-history",
          type: "extract",
          config: { from: "tool_result", at: "tool_call" },
        },
        {
          id: "tool-field",
          type: "tool_extract",
          config: { tools: { exclude: ["read_file"] }, field: "to" },
        },
        { id: "check", type: "regex", config: { pattern: "." } },
      ],
      edges: [{ src: "tool-field", dst: "check" }],
    };

    const editor = toEditorGraph(redesigned);

    expect(editor.nodes.map((node) => node.data.checkpoint)).toEqual([
      "tool_call",
      "tool_call",
      "tool_call",
    ]);
    expect(toGuardrailGraph(editor)).toEqual(redesigned);
  });

  it("옛 extract checkpoint 그래프를 열고 왕복 보존한다", () => {
    const legacy: GuardrailGraph = {
      nodes: [
        {
          id: "legacy-source",
          type: "extract",
          config: { checkpoint: "input", futureField: true },
        },
      ],
      edges: [],
    };

    const editor = toEditorGraph(legacy);

    expect(editor.nodes[0].data.checkpoint).toBe("input");
    expect(toGuardrailGraph(editor)).toEqual(legacy);
  });
});
