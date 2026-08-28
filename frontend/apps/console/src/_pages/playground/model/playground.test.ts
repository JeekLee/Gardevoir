import { describe, expect, it } from "vitest";

import type {
  GuardrailGraph,
  GuardrailTestCheckpoint,
  GuardrailTestResult,
} from "@/src/entities/guardrail";

import {
  actionForCheckpoint,
  blockedCheckpoint,
  diffText,
  firedNodeTraces,
} from "./playground";

const graph: GuardrailGraph = {
  nodes: [
    { id: "source", type: "extract", config: { checkpoint: "input" } },
    { id: "pii", type: "regex", config: { pattern: "[0-9]{6}-[0-9]{7}" } },
    {
      id: "pii-verdict",
      type: "verdict",
      config: { code: "pii-output", action: "mask", combine: "any" },
    },
    { id: "model", type: "model", config: { policy: "유해 요청인가" } },
    {
      id: "harm-verdict",
      type: "verdict",
      config: { action: "block", combine: "any" },
    },
  ],
  edges: [
    { src: "source", dst: "pii" },
    { src: "pii", dst: "pii-verdict" },
    { src: "source", dst: "model" },
    { src: "model", dst: "harm-verdict" },
  ],
};

describe("playground result projection", () => {
  it("발화 코드로 verdict와 상류 체인을 찾는다", () => {
    expect(firedNodeTraces(graph, ["pii-output"])).toEqual([
      {
        code: "pii-output",
        verdict: graph.nodes[2],
        upstream: [graph.nodes[0], graph.nodes[1]],
      },
    ]);
  });

  it("같은 발화 코드는 체크포인트와 실제 정규식 매치로 한 노드에 좁힌다", () => {
    const duplicateGraph: GuardrailGraph = {
      nodes: [
        { id: "input", type: "extract", config: { checkpoint: "input" } },
        { id: "output", type: "extract", config: { checkpoint: "output" } },
        { id: "ssn", type: "regex", config: { pattern: "[0-9]{6}-[0-9]{7}" } },
        { id: "phone", type: "regex", config: { pattern: "010-[0-9]{4}-[0-9]{4}" } },
        { id: "output-ssn", type: "regex", config: { pattern: "[0-9]{6}-[0-9]{7}" } },
        {
          id: "ssn-verdict",
          type: "verdict",
          config: { code: "pii-output", action: "mask" },
        },
        {
          id: "phone-verdict",
          type: "verdict",
          config: { code: "pii-output", action: "mask" },
        },
        {
          id: "output-verdict",
          type: "verdict",
          config: { code: "pii-output", action: "mask" },
        },
      ],
      edges: [
        { src: "input", dst: "ssn" },
        { src: "input", dst: "phone" },
        { src: "output", dst: "output-ssn" },
        { src: "ssn", dst: "ssn-verdict" },
        { src: "phone", dst: "phone-verdict" },
        { src: "output-ssn", dst: "output-verdict" },
      ],
    };

    expect(
      firedNodeTraces(
        duplicateGraph,
        ["pii-output"],
        "input",
        "주민번호 801209-1234567",
      ).map(({ verdict }) => verdict.id),
    ).toEqual(["ssn-verdict"]);
  });

  it("dry-run에서는 적용 action 대신 발화 verdict의 예정 action을 보여준다", () => {
    const checkpoint = checkpointResult({ checksFired: ["harm-verdict"] });
    expect(actionForCheckpoint(graph, checkpoint, "dry-run")).toBe("block");
    expect(
      blockedCheckpoint({
        graph,
        mode: "dry-run",
        result: testResult({ input: checkpoint }),
      }),
    ).toBe("input");
  });

  it("원문과 여러 마스킹 치환을 각각 강조한다", () => {
    const diff = diffText(
      "주민번호 801209-1234567, 연락처 010-1234-5678",
      "주민번호 [개인정보 삭제됨], 연락처 [개인정보 삭제됨]",
    );

    expect(diff.changed).toBe(true);
    expect(diff.raw.filter((part) => part.changed).map((part) => part.text)).toEqual([
      "801209-1234567",
      "010-1234-5678",
    ]);
    expect(
      diff.applied.filter((part) => part.changed).map((part) => part.text),
    ).toEqual(["[개인정보 삭제됨]", "[개인정보 삭제됨]"]);
  });
});

function checkpointResult(
  overrides: Partial<GuardrailTestCheckpoint> = {},
): GuardrailTestCheckpoint {
  return {
    ran: true,
    action: "allow",
    checksFired: [],
    masked: false,
    evidence: [],
    tier: "rules",
    rawText: "요청",
    appliedText: "요청",
    ...overrides,
  };
}

function testResult(
  checkpointOverrides: Partial<
    GuardrailTestResult["checkpoints"]
  > = {},
): GuardrailTestResult {
  return {
    guardrail: "default",
    version: "5",
    model: "model",
    checkpoints: {
      input: checkpointResult(),
      toolResult: checkpointResult({ ran: false, tier: "" }),
      output: checkpointResult(),
      toolCall: checkpointResult({ ran: false, tier: "" }),
      ...checkpointOverrides,
    },
    overallAction: "allow",
    blocked: false,
    blockedAt: null,
    blockedReason: null,
    rawContent: "응답",
    appliedContent: "응답",
    toolCalls: [],
    auditId: null,
    latencyMs: 1,
    unmaskable: 0,
  };
}
