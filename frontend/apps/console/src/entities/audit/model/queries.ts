import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import {
  getAuditEvent,
  getAuditInsights,
  getAuditSummary,
  listAuditEvents,
} from "../api/audit-api";
import type { AuditFilters } from "./audit";

export const auditKeys = {
  all: ["audit"] as const,
  list: (filters: AuditFilters) => ["audit", "list", filters] as const,
  summary: (filters: AuditFilters) => ["audit", "summary", filters] as const,
  insights: (filters: AuditFilters) => ["audit", "insights", filters] as const,
  detail: (eventId: string) => ["audit", "detail", eventId] as const,
};

export function auditListOptions(
  accessToken: string,
  filters: AuditFilters,
) {
  return infiniteQueryOptions({
    queryKey: auditKeys.list(filters),
    queryFn: ({ pageParam, signal }) =>
      listAuditEvents(accessToken, filters, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    staleTime: 10_000,
  });
}

export function auditSummaryOptions(
  accessToken: string,
  filters: AuditFilters,
) {
  return queryOptions({
    queryKey: auditKeys.summary(filters),
    queryFn: ({ signal }) => getAuditSummary(accessToken, filters, signal),
    staleTime: 10_000,
  });
}

export function auditInsightsOptions(
  accessToken: string,
  filters: AuditFilters,
) {
  return queryOptions({
    queryKey: auditKeys.insights(filters),
    queryFn: ({ signal }) => getAuditInsights(accessToken, filters, signal),
    staleTime: 10_000,
  });
}

export function auditDetailOptions(accessToken: string, eventId: string) {
  return queryOptions({
    queryKey: auditKeys.detail(eventId),
    queryFn: ({ signal }) => getAuditEvent(accessToken, eventId, signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
}
