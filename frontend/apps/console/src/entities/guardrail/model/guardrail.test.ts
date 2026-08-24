import { describe, expect, it } from "vitest";

import { parseGuardrailDetail, parseGuardrailPage } from "./guardrail";

describe("guardrail response parsing", () => {
  it("parses camelCase list and detail responses", () => {
    expect(
      parseGuardrailPage({
        items: [
          {
            name: "agent-actions",
            latestVersionNumber: 3,
            hasDraft: true,
            updatedAt: "2026-08-24T00:00:00Z",
          },
        ],
        total: 1,
      }).items[0],
    ).toMatchObject({ name: "agent-actions", latestVersionNumber: 3 });

    expect(
      parseGuardrailDetail({
        name: "agent-actions",
        version: "draft",
        versionNumber: null,
        graph: { nodes: [], edges: [] },
        createdAt: "2026-08-24T00:00:00Z",
        updatedAt: "2026-08-24T00:00:00Z",
      }).graph,
    ).toEqual({ nodes: [], edges: [] });
  });

  it("rejects node types the editor cannot represent", () => {
    expect(() =>
      parseGuardrailDetail({
        name: "future-policy",
        version: "draft",
        versionNumber: null,
        graph: {
          nodes: [{ id: "new", type: "future_node", config: {} }],
          edges: [],
        },
        createdAt: "2026-08-24T00:00:00Z",
        updatedAt: "2026-08-24T00:00:00Z",
      }),
    ).toThrow("Invalid guardrail node response");
  });
});
