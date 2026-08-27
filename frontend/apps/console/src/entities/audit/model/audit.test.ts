import { describe, expect, it } from "vitest";

import {
  parseAuditEventDetail,
  parseAuditEventPage,
  parseAuditSummary,
} from "./audit";

const event = {
  id: "01TEST",
  createdAt: "2026-08-26T08:00:00+00:00",
  appName: "console-smoke",
  guardrail: "pii-mask",
  guardrailVersion: 3,
  mode: "enforce",
  action: "mask",
  checkpoint: "output",
  checksFired: ["pii-output"],
  tierReached: "rule",
  tainted: false,
  latencyMs: 0.42,
  model: "smoke-model",
};

describe("audit response parsers", () => {
  it("parses keyset pages and effective mask actions", () => {
    expect(
      parseAuditEventPage({ items: [event], nextCursor: "next-page" }),
    ).toEqual({ items: [event], nextCursor: "next-page" });
  });

  it("preserves structured verdict evidence in detail", () => {
    const detail = parseAuditEventDetail({
      ...event,
      requestId: "request-1",
      apiKeyId: "key-1",
      verdicts: {
        masked: true,
        evidence: [{ check: "pii-output", count: 1 }],
      },
      promptTokens: 12,
      completionTokens: 4,
      contentFingerprint:
        "f93c6b3565b9cf1be9fbcf2720774505af0d52a1be72357f616cb7d3d6b0f984",
      excerpt: "주민번호 ******-*******",
      inputBody: '{"messages":[{"role":"user","content":"안녕하세요"}]}',
      outputBody: '{"choices":[]}',
      toolCallsBody: "[]",
    });

    expect(detail.verdicts).toEqual({
      masked: true,
      evidence: [{ check: "pii-output", count: 1 }],
    });
    expect(detail.excerpt).toBe("주민번호 ******-*******");
    expect(detail.contentFingerprint).toHaveLength(64);
    expect(detail.inputBody).toContain('"messages"');
  });

  it("rejects detail responses without audit content fields", () => {
    expect(() =>
      parseAuditEventDetail({
        ...event,
        requestId: "request-1",
        apiKeyId: "key-1",
        verdicts: null,
        promptTokens: 0,
        completionTokens: 0,
      }),
    ).toThrow("Invalid audit detail response");
  });

  it("rejects malformed aggregate counts", () => {
    expect(() =>
      parseAuditSummary({
        countsByAction: { allow: -1 },
        latencyP50: 1,
        latencyP95: 2,
        total: 1,
      }),
    ).toThrow("Invalid audit summary response");
  });
});
