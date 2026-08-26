import { describe, expect, it } from "vitest";

import { providerApiKeyChange } from "./api-key-change";

describe("providerApiKeyChange", () => {
  it("편집 중 빈 키는 저장된 키를 유지하는 null sentinel로 바꾼다", () => {
    expect(
      providerApiKeyChange({
        isEditing: true,
        draft: "",
        removeConfirmed: false,
      }),
    ).toBeNull();
  });

  it("확인한 제거만 빈 키로 명시한다", () => {
    expect(
      providerApiKeyChange({
        isEditing: true,
        draft: "",
        removeConfirmed: true,
      }),
    ).toBe("");
  });

  it("새 키와 신규 프로바이더의 빈 키는 그대로 전송한다", () => {
    expect(
      providerApiKeyChange({
        isEditing: true,
        draft: "replacement-key",
        removeConfirmed: false,
      }),
    ).toBe("replacement-key");
    expect(
      providerApiKeyChange({
        isEditing: false,
        draft: "",
        removeConfirmed: false,
      }),
    ).toBe("");
  });
});
