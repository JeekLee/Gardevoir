import { describe, expect, it } from "vitest";

import { formatAuditBody } from "./format-audit-body";

describe("formatAuditBody", () => {
  it("formats JSON bodies", () => {
    expect(formatAuditBody('{"messages":[{"role":"user"}]}')).toBe(
      '{\n  "messages": [\n    {\n      "role": "user"\n    }\n  ]\n}',
    );
  });

  it("preserves a body that is not JSON", () => {
    expect(formatAuditBody("upstream response was not JSON")).toBe(
      "upstream response was not JSON",
    );
  });
});
