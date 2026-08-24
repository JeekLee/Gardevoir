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
      id: "decision",
      type: "verdict",
      config: {
        action: "block",
        code: "secret-found",
        decision: "conclusive",
      },
    },
  ],
  edges: [
    { src: "source", dst: "match" },
    { src: "match", dst: "decision" },
  ],
};

describe("guardrail graph mapper", () => {
  it("preserves domain identity, config, and declaration order through the editor", () => {
    const roundTrip = toGuardrailGraph(toEditorGraph(graph));

    expect(roundTrip).toEqual(graph);
    expect(roundTrip.nodes.map((node) => node.id)).toEqual([
      "source",
      "match",
      "decision",
    ]);
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
});
