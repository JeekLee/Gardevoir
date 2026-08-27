import { expect, it } from "vitest";

import type { GuardrailGraph } from "@/src/entities/guardrail";

import { hasUpstreamNodeType } from "./connections";
import { toEditorGraph } from "./graph-mapper";

function graph(edges: GuardrailGraph["edges"]): GuardrailGraph {
  return {
    nodes: [
      {
        id: "extract",
        type: "extract",
        config: { checkpoint: "input" },
      },
      {
        id: "model",
        type: "model",
        config: { checkpoint: "input", policy: "민감정보인가?" },
      },
      { id: "transform", type: "transform", config: { op: "lower" } },
      { id: "regex", type: "regex", config: { pattern: "secret" } },
      { id: "verdict", type: "verdict", config: { action: "mask" } },
    ],
    edges,
  };
}

it("MODEL Check의 직·간접 verdict 기여를 상류 추적으로 찾는다", () => {
  const direct = toEditorGraph(
    graph([
      { src: "extract", dst: "model" },
      { src: "model", dst: "verdict" },
    ]),
  );
  const transitive = toEditorGraph(
    graph([
      { src: "extract", dst: "model" },
      { src: "model", dst: "transform" },
      { src: "transform", dst: "verdict" },
    ]),
  );
  const regexOnly = toEditorGraph(
    graph([
      { src: "extract", dst: "regex" },
      { src: "regex", dst: "verdict" },
    ]),
  );

  expect(hasUpstreamNodeType(direct, "verdict", "model")).toBe(true);
  expect(hasUpstreamNodeType(transitive, "verdict", "model")).toBe(true);
  expect(hasUpstreamNodeType(regexOnly, "verdict", "model")).toBe(false);
});
