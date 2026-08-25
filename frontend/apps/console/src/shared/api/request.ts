type JsonObject = Record<string, unknown>;

type RequestBase = {
  path: `/${string}`;
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  accessToken?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
};

type JsonRequest<T> = RequestBase & {
  parse: (value: unknown) => T;
};

type EmptyRequest = RequestBase & {
  parse?: never;
};

export class ConsoleApiError extends Error {
  readonly httpStatus: number;
  readonly code: string;
  readonly details?: JsonObject;
  readonly requestId?: string;

  constructor(input: {
    httpStatus: number;
    code: string;
    message: string;
    details?: JsonObject;
    requestId?: string;
  }) {
    super(input.message);
    this.name = "ConsoleApiError";
    this.httpStatus = input.httpStatus;
    this.code = input.code;
    this.details = input.details;
    this.requestId = input.requestId;
  }
}

export function apiRequest(options: EmptyRequest): Promise<void>;
export function apiRequest<T>(options: JsonRequest<T>): Promise<T>;
export async function apiRequest<T>(
  options: EmptyRequest | JsonRequest<T>,
): Promise<void | T> {
  const apiBase = (
    process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:21000/v1"
  ).replace(/\/+$/, "");
  const headers = new Headers({ Accept: "application/json" });
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (options.accessToken) {
    headers.set("Authorization", `Bearer ${options.accessToken}`);
  }

  const timeout = createTimeoutSignal(options.signal, options.timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${apiBase}${options.path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
      signal: timeout.signal,
    });
  } catch (error) {
    if (options.signal?.aborted) {
      throw error;
    }

    throw new ConsoleApiError({
      httpStatus: 0,
      code: timeout.didExpire() ? "CONSOLE-002" : "CONSOLE-001",
      message: timeout.didExpire()
        ? "The gateway did not respond in time."
        : "The console could not reach the gateway.",
    });
  } finally {
    timeout.dispose();
  }

  if (!response.ok) {
    throw await toConsoleError(response);
  }

  if (response.status === 204) {
    return;
  }

  if (!("parse" in options) || !options.parse) {
    return;
  }

  let value: unknown;
  try {
    value = await response.json();
    return options.parse(value);
  } catch (error) {
    if (error instanceof ConsoleApiError) {
      throw error;
    }
    throw new ConsoleApiError({
      httpStatus: response.status,
      code: "CONSOLE-003",
      message: "The gateway returned an unexpected response.",
      requestId: response.headers.get("x-request-id") ?? undefined,
    });
  }
}

async function toConsoleError(response: Response): Promise<ConsoleApiError> {
  const requestIdHeader = response.headers.get("x-request-id") ?? undefined;
  let body: unknown;

  try {
    body = await response.json();
  } catch {
    body = undefined;
  }

  if (isErrorEnvelope(body)) {
    return new ConsoleApiError({
      httpStatus: response.status,
      code: body.code,
      message: body.message,
      details: isJsonObject(body.details) ? body.details : undefined,
      requestId:
        typeof body.requestId === "string" ? body.requestId : requestIdHeader,
    });
  }

  return new ConsoleApiError({
    httpStatus: response.status,
    code: "CONSOLE-004",
    message: "The gateway could not complete this request.",
    requestId: requestIdHeader,
  });
}

function isErrorEnvelope(
  value: unknown,
): value is JsonObject & { code: string; message: string } {
  return (
    isJsonObject(value) &&
    typeof value.code === "string" &&
    typeof value.message === "string"
  );
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function createTimeoutSignal(source?: AbortSignal, timeoutMs = 15_000) {
  const controller = new AbortController();
  let expired = false;
  const abortFromSource = () => controller.abort(source?.reason);

  if (source?.aborted) {
    abortFromSource();
  } else {
    source?.addEventListener("abort", abortFromSource, { once: true });
  }

  const timeoutId = setTimeout(() => {
    expired = true;
    controller.abort();
  }, timeoutMs);

  return {
    signal: controller.signal,
    didExpire: () => expired,
    dispose: () => {
      clearTimeout(timeoutId);
      source?.removeEventListener("abort", abortFromSource);
    },
  };
}
