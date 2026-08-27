import { describe, expect, it } from "vitest";

import { ConsoleApiError } from "./request";
import { consoleErrorMessage, consoleErrorReference } from "./error-message";

describe("console error copy", () => {
  it("게이트웨이 영문 메시지 대신 오류 코드에 맞는 한국어 안내를 표시한다", () => {
    const error = new ConsoleApiError({
      httpStatus: 422,
      code: "GUARDRAIL-012",
      message: "a node has the wrong number of inputs",
      requestId: "req-test",
    });

    expect(consoleErrorMessage(error)).toBe(
      "노드의 입력 연결 수가 올바르지 않습니다.",
    );
    expect(consoleErrorReference(error)).toBe(
      "참조: GUARDRAIL-012 · 요청 ID req-test",
    );
  });

  it("알 수 없는 오류도 상태에 맞는 한국어 조치 문구를 제공한다", () => {
    expect(
      consoleErrorMessage({ code: "UNKNOWN-001", httpStatus: 409 }),
    ).toBe(
      "현재 상태와 충돌했습니다. 최신 내용을 불러오세요.",
    );
  });
});
