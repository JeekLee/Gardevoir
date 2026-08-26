import { describe, expect, it } from "vitest";

import type { EditorGraph } from "./graph-mapper";
import {
  clearRecoveredDraft,
  peekRecoveredDraft,
  preserveRecoveredDraft,
} from "./draft-recovery";

describe("draft recovery", () => {
  it("재인증 이동 중인 편집 그래프를 메모리에서 복구한다", () => {
    const graph: EditorGraph = {
      nodes: [
        {
          id: "input",
          type: "guardrail",
          position: { x: 0, y: 0 },
          data: {
            checkpoint: "input",
            domainNode: {
              id: "input",
              type: "extract",
              config: { checkpoint: "input" },
            },
          },
        },
      ],
      edges: [],
    };

    preserveRecoveredDraft("draft-name", graph);
    expect(peekRecoveredDraft("draft-name")).toBe(graph);
    clearRecoveredDraft("draft-name");
    expect(peekRecoveredDraft("draft-name")).toBeNull();
  });
});
