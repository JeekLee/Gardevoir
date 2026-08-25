import { apiStream, ConsoleApiError } from "@/src/shared/api";

import {
  GuardrailTestStreamParser,
  type GuardrailTestPre,
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
    onPre: (pre: GuardrailTestPre) => void;
    onDelta: (content: string) => void;
  },
): Promise<GuardrailTestResult> {
  const parser = new GuardrailTestStreamParser();
  let result: GuardrailTestResult | null = null;
  let receivedPre = false;
  let receivedDelta = false;
  const consume = (events: GuardrailTestStreamEvent[]) => {
    for (const event of events) {
      if (event.type === "pre") {
        if (receivedPre || receivedDelta || result !== null) {
          throw unexpectedStream();
        }
        receivedPre = true;
        input.onPre(event.pre);
      } else if (event.type === "delta") {
        if (!receivedPre || result !== null) throw unexpectedStream();
        receivedDelta = true;
        input.onDelta(event.content);
      } else {
        if (!receivedPre || result !== null) throw unexpectedStream();
        result = event.result;
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
        mode: "enforce",
      },
      onChunk: (chunk) => consume(parser.push(chunk)),
      timeoutMs: 120_000,
    });
    consume(parser.finish());
  } catch (error) {
    if (error instanceof ConsoleApiError || input.signal.aborted) throw error;
    throw unexpectedStream();
  }

  if (!receivedPre || result === null) throw unexpectedStream();
  return result;
}

function unexpectedStream(): ConsoleApiError {
  return new ConsoleApiError({
    httpStatus: 200,
    code: "CONSOLE-003",
    message: "The gateway returned an unexpected response.",
  });
}
