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

type StreamRequest = RequestBase & {
  onChunk: (chunk: Uint8Array) => void | Promise<void>;
};

type SessionRecovery = (expiredAccessToken: string) => Promise<string | null>;

let sessionRecovery: SessionRecovery | null = null;

export function setSessionRecovery(recovery: SessionRecovery | null): void {
  sessionRecovery = recovery;
}

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
  return apiRequestAttempt(options, true);
}

async function apiRequestAttempt<T>(
  options: EmptyRequest | JsonRequest<T>,
  allowSessionRecovery: boolean,
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
        ? "게이트웨이 응답 시간이 초과되었습니다."
        : "게이트웨이에 연결할 수 없습니다.",
    });
  } finally {
    timeout.dispose();
  }

  if (
    response.status === 401 &&
    options.accessToken &&
    allowSessionRecovery &&
    sessionRecovery
  ) {
    const recoveredAccessToken = await sessionRecovery(options.accessToken);
    if (recoveredAccessToken) {
      return apiRequestAttempt(
        { ...options, accessToken: recoveredAccessToken },
        false,
      );
    }
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
      message: "게이트웨이 응답 형식을 확인할 수 없습니다.",
      requestId: response.headers.get("x-request-id") ?? undefined,
    });
  }
}

export async function apiStream(options: StreamRequest): Promise<void> {
  return apiStreamAttempt(options, true);
}

async function apiStreamAttempt(
  options: StreamRequest,
  allowSessionRecovery: boolean,
): Promise<void> {
  const apiBase = (
    process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:21000/v1"
  ).replace(/\/+$/, "");
  const headers = new Headers({ Accept: "text/event-stream" });
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (options.accessToken) {
    headers.set("Authorization", `Bearer ${options.accessToken}`);
  }

  const timeout = createTimeoutSignal(options.signal, options.timeoutMs);
  try {
    let response: Response;
    try {
      response = await fetch(`${apiBase}${options.path}`, {
        method: options.method ?? "GET",
        headers,
        body:
          options.body === undefined ? undefined : JSON.stringify(options.body),
        cache: "no-store",
        signal: timeout.signal,
      });
    } catch (error) {
      throw normalizeTransportError(error, options.signal, timeout.didExpire());
    }

    if (
      response.status === 401 &&
      options.accessToken &&
      allowSessionRecovery &&
      sessionRecovery
    ) {
      const recoveredAccessToken = await sessionRecovery(options.accessToken);
      if (recoveredAccessToken) {
        return apiStreamAttempt(
          { ...options, accessToken: recoveredAccessToken },
          false,
        );
      }
    }

    if (!response.ok) {
      throw await toConsoleError(response);
    }
    if (!response.body) {
      throw unexpectedResponse(response);
    }

    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().startsWith("text/event-stream")) {
      throw unexpectedResponse(response);
    }

    const reader = response.body.getReader();
    try {
      while (true) {
        let read: ReadableStreamReadResult<Uint8Array>;
        try {
          read = await reader.read();
        } catch (error) {
          throw normalizeTransportError(
            error,
            options.signal,
            timeout.didExpire(),
          );
        }
        if (read.done) return;
        try {
          await options.onChunk(read.value);
        } catch (error) {
          await reader.cancel();
          throw error;
        }
      }
    } finally {
      reader.releaseLock();
    }
  } finally {
    timeout.dispose();
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
    message: "게이트웨이가 요청을 처리하지 못했습니다.",
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

function unexpectedResponse(response: Response): ConsoleApiError {
  return new ConsoleApiError({
    httpStatus: response.status,
    code: "CONSOLE-003",
    message: "게이트웨이 응답 형식을 확인할 수 없습니다.",
    requestId: response.headers.get("x-request-id") ?? undefined,
  });
}

function normalizeTransportError(
  error: unknown,
  source: AbortSignal | undefined,
  expired: boolean,
): unknown {
  if (source?.aborted) {
    return error;
  }
  return new ConsoleApiError({
    httpStatus: 0,
    code: expired ? "CONSOLE-002" : "CONSOLE-001",
    message: expired
      ? "게이트웨이 응답 시간이 초과되었습니다."
      : "게이트웨이에 연결할 수 없습니다.",
  });
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
