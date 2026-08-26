import { describe, expect, it } from "vitest";

import { isFutureDateTime, toAwareIso } from "./date-input";

describe("API key expiry input", () => {
  it("브라우저 로컬 시각을 시간대가 포함된 ISO 문자열로 바꾼다", () => {
    const iso = toAwareIso("2026-08-27T12:30");
    expect(iso).toMatch(/^2026-08-27T\d{2}:30:00\.000Z$/);
  });

  it("과거 만료 시각을 거부한다", () => {
    expect(
      isFutureDateTime(
        "2026-08-26T10:00",
        new Date("2026-08-27T00:00:00Z"),
      ),
    ).toBe(false);
  });
});
