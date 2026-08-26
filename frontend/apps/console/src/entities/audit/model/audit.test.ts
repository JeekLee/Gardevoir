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
    });

    expect(detail.verdicts).toEqual({
      masked: true,
      evidence: [{ check: "pii-output", count: 1 }],
    });
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
