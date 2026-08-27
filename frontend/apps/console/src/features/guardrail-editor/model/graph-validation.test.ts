import { describe, expect, it } from "vitest";

import type { GuardrailGraph } from "@/src/entities/guardrail";

import { toEditorGraph } from "./graph-mapper";
import { validateEditorGraph } from "./graph-validation";

describe("guardrail editor validation", () => {
  it("MODEL 정책 질의가 비어 있으면 저장 전에 노드 오류를 반환한다", () => {
    const graph: GuardrailGraph = {
      nodes: [
        {
          id: "model-check",
          type: "model",
          config: { policy: "   ", strictness: "strict", checkpoint: "input" },
        },
      ],
      edges: [],
    };

    expect(validateEditorGraph(toEditorGraph(graph))).toEqual([
      {
        nodeId: "model-check",
        message: "MODEL 검사의 자연어 정책 질의를 입력하세요.",
      },
    ]);
  });

  it("MODEL 정책 질의가 있으면 로컬 검증을 통과한다", () => {
    const graph: GuardrailGraph = {
      nodes: [
        {
          id: "model-check",
          type: "model",
          config: {
            policy: "개인정보를 노출하는가?",
            strictness: "balanced",
            checkpoint: "output",
          },
        },
      ],
      edges: [],
    };

    expect(validateEditorGraph(toEditorGraph(graph))).toEqual([]);
  });
});
