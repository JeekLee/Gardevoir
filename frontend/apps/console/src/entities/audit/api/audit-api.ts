import { apiRequest } from "@/src/shared/api";

import {
  parseAuditEventDetail,
  parseAuditEventPage,
  parseAuditSummary,
  type AuditFilters,
} from "../model/audit";

const PAGE_SIZE = 50;

export function listAuditEvents(
  accessToken: string,
  filters: AuditFilters,
  cursor: string | null,
  signal?: AbortSignal,
) {
  const search = auditSearch(filters);
  search.set("limit", String(PAGE_SIZE));
  if (cursor) search.set("cursor", cursor);
  return apiRequest({
    path: `/audit?${search.toString()}`,
    accessToken,
    signal,
    parse: parseAuditEventPage,
  });
}

export function getAuditSummary(
  accessToken: string,
  filters: AuditFilters,
  signal?: AbortSignal,
) {
  const search = auditSearch(filters).toString();
  return apiRequest({
    path: search ? `/audit/summary?${search}` : "/audit/summary",
    accessToken,
    signal,
    parse: parseAuditSummary,
  });
}

export function getAuditEvent(
  accessToken: string,
  eventId: string,
  signal?: AbortSignal,
) {
  return apiRequest({
    path: `/audit/${encodeURIComponent(eventId)}`,
    accessToken,
    signal,
    parse: parseAuditEventDetail,
  });
}

function auditSearch(filters: AuditFilters): URLSearchParams {
  const search = new URLSearchParams();
  const strings: [string, string | undefined][] = [
    ["appName", filters.appName],
    ["guardrail", filters.guardrail],
    ["action", filters.action],
    ["checkpoint", filters.checkpoint],
    ["mode", filters.mode],
    ["from", filters.from],
    ["to", filters.to],
  ];
  for (const [name, value] of strings) {
    if (value) search.set(name, value);
  }
  if (filters.tainted !== undefined) {
    search.set("tainted", String(filters.tainted));
  }
  return search;
}
