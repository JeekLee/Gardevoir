import { describe, expect, it } from "vitest";

import { buildAppConnectionSnippet } from "./app-connection";
import {
  apiKeyStatus,
  parseApiKeyCreated,
  parseApiKeyPage,
} from "./api-key";

describe("API key response parsing", () => {
  it("목록에는 미리보기만 남기고 생성 응답의 평문 키를 분리한다", () => {
    const page = parseApiKeyPage({
      items: [
        {
          id: "key-id",
          name: "production",
          keyPreview: "gdv_live_…a1b2",
          expiresAt: null,
          revokedAt: null,
          createdAt: "2026-08-26T01:00:00Z",
          updatedAt: "2026-08-26T01:00:00Z",
          key: "gdv_live_secret",
        },
      ],
      total: 1,
    });
    const created = parseApiKeyCreated({
      id: "key-id",
      name: "production",
      key: "gdv_live_secret",
      expiresAt: null,
    });

    expect(page.items[0]).toEqual({
      id: "key-id",
      name: "production",
      keyPreview: "gdv_live_…a1b2",
      expiresAt: null,
      revokedAt: null,
      createdAt: "2026-08-26T01:00:00Z",
      updatedAt: "2026-08-26T01:00:00Z",
    });
    expect(created.key).toBe("gdv_live_secret");
  });

  it("잘못된 목록 계약을 거부한다", () => {
    expect(() => parseApiKeyPage([])).toThrow("Invalid API key list response");
  });

  it("폐기와 만료를 활성 상태보다 우선해 구분한다", () => {
    const now = new Date("2026-08-26T02:00:00Z");
    expect(apiKeyStatus({ expiresAt: null, revokedAt: null }, now)).toBe(
      "active",
    );
    expect(
      apiKeyStatus(
        { expiresAt: "2026-08-26T01:00:00Z", revokedAt: null },
        now,
      ),
    ).toBe("expired");
    expect(
      apiKeyStatus(
        {
          expiresAt: "2026-08-26T01:00:00Z",
          revokedAt: "2026-08-26T00:00:00Z",
        },
        now,
      ),
    ).toBe("revoked");
  });
});

describe("app connection snippet", () => {
  it("dry-run 호출에 필수 헤더와 최소 chat body를 넣는다", () => {
    const snippet = buildAppConnectionSnippet({
      endpoint: "https://gardevoir.example/v1/chat/completions",
      apiKey: "gdv_live_test",
      guardrailName: "agent-actions",
      mode: "dry-run",
    });

    expect(snippet).toContain("Authorization: Bearer gdv_live_test");
    expect(snippet).toContain("X-Gardevoir-Guardrail: agent-actions");
    expect(snippet).toContain("X-Gardevoir-Mode: dry-run");
    expect(snippet).toContain('"model": "gpt-5.2"');
    expect(snippet).toContain('"messages"');
  });

  it("enforce 기본 모드에서는 선택 헤더를 생략한다", () => {
    const snippet = buildAppConnectionSnippet({
      endpoint: "http://localhost:21000/v1/chat/completions",
      apiKey: "gdv_live_...",
      guardrailName: "default",
      mode: "enforce",
    });

    expect(snippet).not.toContain("X-Gardevoir-Mode");
  });
});
