import { describe, expect, it } from "vitest";

import type { GuardrailGraph } from "./guardrail";
import {
  describeGuardrailGraph,
  describeGuardrailSummary,
} from "./policy-summary";

describe("guardrail policy copy", () => {
  it("explains tool-result side effects in operator language", () => {
    const graph: GuardrailGraph = {
      nodes: [
        {
          id: "tainted",
          type: "extract",
          config: { from: "tool_result", at: "tool_call" },
        },
        { id: "tainted-check", type: "regex", config: { pattern: "." } },
        {
          id: "side-effect",
          type: "tool_extract",
          config: { tools: { exclude: [] }, field: "name" },
        },
        {
          id: "block",
          type: "verdict",
          config: { action: "block", combine: "all" },
        },
      ],
      edges: [],
    };

    expect(describeGuardrailGraph(graph)).toBe(
      "오염된 대화에서 부작용 툴 호출을 차단합니다 (② → ④).",
    );
  });

  it("explains output pattern masking", () => {
    const graph: GuardrailGraph = {
      nodes: [
        {
          id: "output",
          type: "extract",
          config: { from: "output_text", at: "output" },
        },
        { id: "pattern", type: "regex", config: { pattern: "secret" } },
        { id: "mask", type: "verdict", config: { action: "mask" } },
      ],
      edges: [],
    };

    expect(describeGuardrailGraph(graph)).toBe(
      "출력에서 패턴이 매칭되면 마스킹합니다 (③).",
    );
  });

  it("summarizes projected policy data and empty drafts", () => {
    expect(
      describeGuardrailSummary({
        checkpoints: ["tool_result", "tool_call"],
        actions: ["block"],
        checkCount: 2,
        verdictCount: 1,
      }),
    ).toBe("툴 결과·툴 호출을 검사해 차단합니다 (② · ④).");

    expect(
      describeGuardrailSummary({
        checkpoints: [],
        actions: [],
        checkCount: 0,
        verdictCount: 0,
      }),
    ).toBe("빈 초안");
  });
});
