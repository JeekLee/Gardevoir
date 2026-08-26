const defaultApiBase = "http://localhost:21000/v1";

export function consoleApiBase(): string {
  return (process.env.NEXT_PUBLIC_API_BASE ?? defaultApiBase).replace(/\/+$/, "");
}

export function proxyChatCompletionsUrl(apiBase = consoleApiBase()): string {
  return `${apiBase.replace(/\/+$/, "")}/chat/completions`;
}
