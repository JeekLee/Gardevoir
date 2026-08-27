export function formatAuditBody(body: string): string {
  try {
    return JSON.stringify(JSON.parse(body), null, 2) ?? body;
  } catch {
    return body;
  }
}
