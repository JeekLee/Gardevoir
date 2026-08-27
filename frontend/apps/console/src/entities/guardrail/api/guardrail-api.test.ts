import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteGuardrail } from "./guardrail-api";

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
