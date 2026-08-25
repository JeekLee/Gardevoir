import { describe, expect, it } from "vitest";

import type { GuardrailGraph } from "@/src/entities/guardrail";
import type { ProviderSummary } from "@/src/entities/provider";

import {
  GuardrailTestStreamParser,
  parseGuardrailTestResult,
  providerModelOptions,
  testHighlights,
} from "./guardrail-test";

describe("guardrail test result", () => {
  it("체크포인트별 요청 원본·적용 텍스트와 모델 응답을 파싱한다", () => {
    const result = parseGuardrailTestResult({
      guardrail: "default",
      version: "draft",
      model: "local-model",
      checkpoints: {
        input: checkpoint({
          action: "mask",
          checksFired: ["input-secret"],
          masked: true,
          rawText: "주민번호는 900101-1234567입니다.",
          appliedText: "주민번호는 [개인정보 삭제됨]입니다.",
        }),
        toolResult: checkpoint({
          action: "mask",
          checksFired: ["tool-secret"],
          masked: true,
          rawText: "조회 결과 801209-1234567",
          appliedText: "조회 결과 [개인정보 삭제됨]",
        }),
        output: checkpoint({ action: "mask", masked: true }),
        toolCall: checkpoint({
          evidence: [{ tool: "send_email", arguments: ["to"] }],
        }),
      },
      overallAction: "mask",
      blocked: false,
      blockedAt: null,
      blockedReason: null,
      rawContent: "주민번호는 900101-1234567입니다.",
      appliedContent: "주민번호는 [개인정보 삭제됨]입니다.",
      toolCalls: [],
      auditId: null,
      latencyMs: 42.25,
      unmaskable: 1,
    });

    expect(result.overallAction).toBe("mask");
    expect(result.checkpoints.input.checksFired).toEqual(["input-secret"]);
    expect(result.checkpoints.input.action).toBe("mask");
    expect(result.checkpoints.input.masked).toBe(true);
    expect(result.checkpoints.input.rawText).toContain("900101-1234567");
    expect(result.checkpoints.input.appliedText).toContain("[개인정보 삭제됨]");
    expect(result.checkpoints.toolResult.rawText).toContain("801209-1234567");
    expect(result.checkpoints.toolResult.appliedText).toContain("[개인정보 삭제됨]");
    expect(result.checkpoints.output.action).toBe("mask");
    expect(result.checkpoints.toolCall.evidence[0]).toEqual({
      tool: "send_email",
      arguments: ["to"],
    });
    expect(result.rawContent).toContain("900101-1234567");
    expect(result.appliedContent).toContain("[개인정보 삭제됨]");
    expect(result.unmaskable).toBe(1);
  });

  it("업스트림 이전 결과와 OpenAI SSE delta, 종료 결과를 순서대로 파싱한다", () => {
    const parser = new GuardrailTestStreamParser();
    const encoder = new TextEncoder();
    const result = {
      guardrail: "default",
      version: "draft",
      model: "local-model",
      checkpoints: {
        input: checkpoint(),
        toolResult: checkpoint(),
        output: checkpoint({ action: "mask", masked: true }),
        toolCall: checkpoint(),
      },
      overallAction: "mask",
      blocked: false,
      blockedAt: null,
      blockedReason: null,
      rawContent: "",
      appliedContent: "[개인정보 삭제됨]",
      toolCalls: [],
      auditId: null,
      latencyMs: 31.5,
      unmaskable: 0,
    };
    const pre = {
      input: checkpoint({
        action: "mask",
        checksFired: ["input-secret"],
        masked: true,
        rawText: "주민번호는 900101-1234567입니다.",
        appliedText: "주민번호는 [개인정보 삭제됨]입니다.",
      }),
      toolResult: checkpoint({ ran: false, tier: "" }),
    };
    const wire = encoder.encode(
      `event: pre\ndata: ${JSON.stringify(pre)}\n\n` +
        'data: {"choices":[{"delta":{"content":"[개인정보 삭제됨]"}}]}' +
        `\r\n\r\ndata: [DONE]\n\nevent: result\ndata: ${JSON.stringify(result)}\n\n`,
    );
    const splitInsideKorean = wire.findIndex((byte) => byte >= 0x80) + 1;
    const source = [
      wire.slice(0, splitInsideKorean),
      wire.slice(splitInsideKorean),
    ];

    const events = source.flatMap((chunk) => parser.push(chunk));
    events.push(...parser.finish());

    expect(events).toHaveLength(3);
    expect(events[0]).toMatchObject({
      type: "pre",
      pre: {
        input: {
          action: "mask",
          appliedText: "주민번호는 [개인정보 삭제됨]입니다.",
        },
      },
    });
    expect(events[1]).toEqual({
      type: "delta",
      content: "[개인정보 삭제됨]",
    });
    expect(events[2]).toMatchObject({
      type: "result",
      result: { overallAction: "mask", unmaskable: 0 },
    });
  });

  it("업스트림 호출 전 차단 결과를 파싱한다", () => {
    const result = parseGuardrailTestResult({
      guardrail: "block-input",
      version: "draft",
      model: "local-model",
      checkpoints: {
        input: checkpoint({
          action: "block",
          checksFired: ["blocked-input"],
        }),
        toolResult: checkpoint({ ran: false, tier: "" }),
        output: checkpoint({ ran: false, tier: "" }),
        toolCall: checkpoint({ ran: false, tier: "" }),
      },
      overallAction: "block",
      blocked: true,
      blockedAt: "input",
      blockedReason: "blocked-input",
      rawContent: "",
      appliedContent: "",
      toolCalls: [],
      auditId: null,
      latencyMs: 0.25,
    });

    expect(result.blocked).toBe(true);
    expect(result.blockedAt).toBe("input");
    expect(result.blockedReason).toBe("blocked-input");
    expect(result.appliedContent).toBe("");
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
    action: "allow",
    checksFired: [],
    masked: false,
    evidence: [],
    tier: "rules",
    rawText: null,
    appliedText: null,
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
