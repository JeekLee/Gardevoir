import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteGuardrail,
  listGuardrailVersions,
  testGuardrail,
} from "./guardrail-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("deleteGuardrail", () => {
  it("관리자 토큰으로 가드레일 전체 삭제를 요청한다", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      deleteGuardrail("access-token", "agent-action-control"),
    ).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://localhost:21000/v1/guardrails/agent-action-control",
    );
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("DELETE");
    expect(
      new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("Authorization"),
    ).toBe("Bearer access-token");
  });
});

describe("playground guardrail requests", () => {
  it("발행 버전 목록을 관리자 계약으로 조회한다", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({
        items: [
          {
            versionNumber: 5,
            publishedAt: "2026-08-28T01:00:00Z",
            description: "기본 정책",
            nodeCount: 12,
            verdictCount: 4,
          },
        ],
        total: 1,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listGuardrailVersions("access-token", "default")).resolves.toMatchObject({
      total: 1,
      items: [{ versionNumber: 5 }],
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://localhost:21000/v1/guardrails/default/versions",
    );
  });

  it("선택한 버전·모드와 이미지 data URI를 기존 test API에 보낸다", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({
        guardrail: "default",
        version: "5",
        model: "qwen3-vl-8b-instruct",
        checkpoints: {
          input: checkpoint(),
          toolResult: checkpoint({ ran: false, tier: "" }),
          output: checkpoint(),
          toolCall: checkpoint({ ran: false, tier: "" }),
        },
        overallAction: "allow",
        blocked: false,
        blockedAt: null,
        blockedReason: null,
        rawContent: "ok",
        appliedContent: "ok",
        toolCalls: [],
        auditId: null,
        latencyMs: 3.2,
        unmaskable: 0,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await testGuardrail("access-token", "default", {
      model: "qwen3-vl-8b-instruct",
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: "이미지를 판정해줘" },
            {
              type: "image_url",
              image_url: { url: "data:image/png;base64,AA==" },
            },
          ],
        },
      ],
      version: "5",
      mode: "dry-run",
    });

    const body = fetchMock.mock.calls[0]?.[1]?.body;
    expect(typeof body).toBe("string");
    expect(JSON.parse(String(body))).toMatchObject({
      version: "5",
      mode: "dry-run",
      messages: [
        {
          content: [
            { type: "text", text: "이미지를 판정해줘" },
            { type: "image_url", image_url: { url: "data:image/png;base64,AA==" } },
          ],
        },
      ],
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
