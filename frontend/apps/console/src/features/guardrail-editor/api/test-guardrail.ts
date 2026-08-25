import { apiStream, ConsoleApiError } from "@/src/shared/api";

import {
  GuardrailTestStreamParser,
  parseGuardrailTestResult,
  type GuardrailTestResult,
  type GuardrailTestStreamEvent,
} from "../model/guardrail-test";

export async function streamGuardrailTest(
  accessToken: string,
  name: string,
  input: {
    model: string;
    message: string;
    signal: AbortSignal;
    onDelta: (content: string) => void;
  },
): Promise<GuardrailTestResult> {
  const parser = new GuardrailTestStreamParser();
  let result: GuardrailTestResult | null = null;
  const consume = (events: GuardrailTestStreamEvent[]) => {
    for (const event of events) {
      if (event.type === "delta") {
        input.onDelta(event.content);
      } else if (result === null) {
        result = parseGuardrailTestResult(event.result);
      } else {
        throw unexpectedStream();
      }
    }
  };

  try {
    await apiStream({
      path: `/guardrails/${encodeURIComponent(name)}/test/stream`,
      method: "POST",
      accessToken,
      signal: input.signal,
      body: {
        model: input.model,
        messages: [{ role: "user", content: input.message }],
        version: "draft",
      },
      onChunk: (chunk) => consume(parser.push(chunk)),
      timeoutMs: 120_000,
    });
    consume(parser.finish());
  } catch (error) {
    if (error instanceof ConsoleApiError || input.signal.aborted) throw error;
    throw unexpectedStream();
  }

  if (result === null) throw unexpectedStream();
  return result;
}

function unexpectedStream(): ConsoleApiError {
  return new ConsoleApiError({
    httpStatus: 200,
    code: "CONSOLE-003",
    message: "The gateway returned an unexpected response.",
  });
}
