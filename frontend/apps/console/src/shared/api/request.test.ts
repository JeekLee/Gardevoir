import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest, apiStream } from "./request";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  it("204 응답을 JSON으로 파싱하지 않는다", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRequest({
        path: "/providers/provider-id",
        method: "DELETE",
        accessToken: "access-token",
      }),
    ).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://localhost:21000/v1/providers/provider-id",
    );
    expect(
      new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("Authorization"),
    ).toBe("Bearer access-token");
  });

  it("게이트웨이 오류 코드와 요청 ID를 보존한다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: "PROVIDER-003",
            message: "another provider already serves this model",
            details: { model: "gpt-5" },
          }),
          {
            status: 409,
            headers: { "x-request-id": "req-test" },
          },
        ),
      ),
    );

    const request = apiRequest({
      path: "/providers",
      method: "POST",
      body: {},
    });

    await expect(request).rejects.toMatchObject({
      httpStatus: 409,
      code: "PROVIDER-003",
      details: { model: "gpt-5" },
      requestId: "req-test",
    });
  });
});

describe("apiStream", () => {
  it("SSE 응답 청크를 도착 순서대로 소비한다", async () => {
    const encoder = new TextEncoder();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode("data: first\n\n"));
              controller.enqueue(encoder.encode("data: second\n\n"));
              controller.close();
            },
          }),
          { headers: { "content-type": "text/event-stream" } },
        ),
      ),
    );
    const chunks: string[] = [];

    await apiStream({
      path: "/guardrails/default/test/stream",
      method: "POST",
      accessToken: "access-token",
      body: {},
      onChunk: (chunk) => {
        chunks.push(new TextDecoder().decode(chunk));
      },
    });

    expect(chunks).toEqual(["data: first\n\n", "data: second\n\n"]);
  });

  it("스트림 시작 전 게이트웨이 오류를 보존한다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ code: "GUARDRAIL-004", message: "invalid draft" }),
          {
            status: 422,
            headers: { "content-type": "application/json" },
          },
        ),
      ),
    );

    await expect(
      apiStream({
        path: "/guardrails/default/test/stream",
        method: "POST",
        body: {},
        onChunk: () => undefined,
      }),
    ).rejects.toMatchObject({ httpStatus: 422, code: "GUARDRAIL-004" });
  });
});
