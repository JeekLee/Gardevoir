import { apiRequest } from "@/src/shared/api";

import {
  parseGuardrailTestResult,
  type GuardrailTestResult,
} from "../model/guardrail-test";

export function testGuardrail(
  accessToken: string,
  name: string,
  input: { model: string; message: string },
): Promise<GuardrailTestResult> {
  return apiRequest({
    path: `/guardrails/${encodeURIComponent(name)}/test`,
    method: "POST",
    accessToken,
    body: {
      model: input.model,
      messages: [{ role: "user", content: input.message }],
      version: "draft",
    },
    parse: parseGuardrailTestResult,
    timeoutMs: 120_000,
  });
}
