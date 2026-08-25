import { describe, expect, it } from "vitest";

import type { GuardrailGraph } from "./guardrail";
import {
  describeGuardrailGraph,
  describeGuardrailSummary,
} from "./policy-summary";

describe("guardrail policy copy", () => {
  it("explains tainted side effects in operator language", () => {
    const graph: GuardrailGraph = {
      nodes: [
        { id: "tainted", type: "taint", config: { checkpoint: "tool_call" } },
        {
          id: "side-effect",
          type: "side_effect",
          config: { checkpoint: "tool_call", read_only: [] },
        },
        { id: "both", type: "all", config: {} },
        {
          id: "block",
          type: "verdict",
          config: { action: "block", decision: "conclusive" },
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
        { id: "output", type: "extract", config: { checkpoint: "output" } },
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
