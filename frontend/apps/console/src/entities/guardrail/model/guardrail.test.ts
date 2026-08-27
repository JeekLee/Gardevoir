import { describe, expect, it } from "vitest";

import { parseGuardrailDetail, parseGuardrailPage } from "./guardrail";

describe("guardrail response parsing", () => {
  it("parses camelCase list and detail responses", () => {
    expect(
      parseGuardrailPage({
        items: [
          {
            name: "agent-actions",
            description: "오염된 대화의 부작용 툴 호출을 차단합니다.",
            latestVersionNumber: 3,
            hasDraft: true,
            updatedAt: "2026-08-24T00:00:00Z",
            checkpoints: ["tool_result", "tool_call"],
            actions: ["block"],
            checkCount: 2,
            verdictCount: 1,
          },
        ],
        total: 1,
      }).items[0],
    ).toMatchObject({
      name: "agent-actions",
      description: "오염된 대화의 부작용 툴 호출을 차단합니다.",
      latestVersionNumber: 3,
      checkpoints: ["tool_result", "tool_call"],
      actions: ["block"],
      checkCount: 2,
      verdictCount: 1,
    });

    expect(
      parseGuardrailDetail({
        name: "agent-actions",
        version: "draft",
        versionNumber: null,
        description: "초안 설명",
        graph: { nodes: [], edges: [] },
        createdAt: "2026-08-24T00:00:00Z",
        updatedAt: "2026-08-24T00:00:00Z",
      }),
    ).toMatchObject({
      description: "초안 설명",
      graph: { nodes: [], edges: [] },
    });
  });

  it("defaults summary projection fields from an older gateway response", () => {
    expect(
      parseGuardrailPage({
        items: [
          {
            name: "legacy-policy",
            description: "",
            latestVersionNumber: null,
            hasDraft: true,
            updatedAt: "2026-08-24T00:00:00Z",
          },
        ],
        total: 1,
      }).items[0],
    ).toMatchObject({
      checkpoints: [],
      actions: [],
      checkCount: 0,
      verdictCount: 0,
    });
  });

  it("rejects node types the editor cannot represent", () => {
    expect(() =>
      parseGuardrailDetail({
        name: "future-policy",
        version: "draft",
        versionNumber: null,
        description: "",
        graph: {
          nodes: [{ id: "new", type: "future_node", config: {} }],
          edges: [],
        },
        createdAt: "2026-08-24T00:00:00Z",
        updatedAt: "2026-08-24T00:00:00Z",
      }),
    ).toThrow("Invalid guardrail node response");
  });

  it("rejects responses without a description", () => {
    expect(() =>
      parseGuardrailDetail({
        name: "missing-description",
        version: "draft",
        versionNumber: null,
        graph: { nodes: [], edges: [] },
        createdAt: "2026-08-24T00:00:00Z",
        updatedAt: "2026-08-24T00:00:00Z",
      }),
    ).toThrow("Invalid guardrail response");
  });
});
