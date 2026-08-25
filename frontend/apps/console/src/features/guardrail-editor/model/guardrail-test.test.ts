import { describe, expect, it } from "vitest";

import type { GuardrailGraph } from "@/src/entities/guardrail";
import type { ProviderSummary } from "@/src/entities/provider";

import {
  parseGuardrailTestResult,
  providerModelOptions,
  testHighlights,
} from "./guardrail-test";

describe("guardrail test result", () => {
  it("실제 호출 결과의 체크포인트와 마스킹 미리보기를 파싱한다", () => {
    const result = parseGuardrailTestResult({
      guardrail: "default",
      version: "draft",
      model: "local-model",
      checkpoints: {
        input: checkpoint({ wouldHave: "block", checksFired: ["input-secret"] }),
        toolResult: checkpoint({ ran: false }),
        output: checkpoint({ wouldHave: "mask", masked: true }),
        toolCall: checkpoint({
          evidence: [{ tool: "send_email", arguments: ["to"] }],
        }),
      },
      overallWouldHave: "block",
      modelResponse: {
        content: "123-45-6789",
        toolCalls: [],
        maskedPreview: "[개인정보 삭제됨]",
      },
      auditId: null,
      latencyMs: 42.25,
    });

    expect(result.overallWouldHave).toBe("block");
    expect(result.checkpoints.input.checksFired).toEqual(["input-secret"]);
    expect(result.checkpoints.toolCall.evidence[0]).toEqual({
      tool: "send_email",
      arguments: ["to"],
    });
    expect(result.modelResponse.maskedPreview).toBe("[개인정보 삭제됨]");
  });

  it("프로바이더 순서를 유지하며 중복 모델을 한 번만 노출한다", () => {
    const providers = [
      provider("local", ["model-a", "model-b"]),
      provider("remote", ["model-b", "model-c"]),
    ];

    expect(providerModelOptions(providers)).toEqual([
      { model: "model-a", provider: "local" },
      { model: "model-b", provider: "local" },
      { model: "model-c", provider: "remote" },
    ]);
  });

  it("걸린 verdict 코드와 연결된 상류 체인을 찾는다", () => {
    const graph: GuardrailGraph = {
      nodes: [
        { id: "source", type: "extract", config: { checkpoint: "input" } },
        { id: "check", type: "regex", config: { pattern: "secret" } },
        {
          id: "decision",
          type: "verdict",
          config: { action: "block", decision: "conclusive", code: "secret-found" },
        },
        {
          id: "other",
          type: "verdict",
          config: { action: "allow", decision: "conclusive", code: "other" },
        },
      ],
      edges: [
        { src: "source", dst: "check" },
        { src: "check", dst: "decision" },
      ],
    };

    expect(testHighlights(graph, ["secret-found"])).toEqual({
      fired: ["decision"],
      upstream: ["check", "source"],
    });
  });
});

function checkpoint(overrides: Record<string, unknown> = {}) {
  return {
    ran: true,
    wouldHave: null,
    checksFired: [],
    masked: false,
    evidence: [],
    tier: "rules",
    ...overrides,
  };
}

function provider(name: string, models: string[]): ProviderSummary {
  return {
    id: name,
    name,
    baseUrl: "http://localhost:8000/v1",
    models,
    hasApiKey: false,
    createdAt: "2026-08-25T00:00:00Z",
    updatedAt: "2026-08-25T00:00:00Z",
  };
}
