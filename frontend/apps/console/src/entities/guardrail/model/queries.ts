import { queryOptions } from "@tanstack/react-query";

import {
  getGuardrailDraft,
  getGuardrailVersion,
  listGuardrails,
} from "../api/guardrail-api";

export const guardrailKeys = {
  all: ["guardrails"] as const,
  list: () => ["guardrails", "list"] as const,
  draft: (name: string) => ["guardrails", name, "draft"] as const,
  version: (name: string, versionNumber: number) =>
    ["guardrails", name, "version", versionNumber] as const,
};

export function guardrailListOptions(accessToken: string) {
  return queryOptions({
    queryKey: guardrailKeys.list(),
    queryFn: ({ signal }) => listGuardrails(accessToken, signal),
    staleTime: 15_000,
  });
}

export function guardrailDraftOptions(accessToken: string, name: string) {
  return queryOptions({
    queryKey: guardrailKeys.draft(name),
    queryFn: ({ signal }) => getGuardrailDraft(accessToken, name, signal),
    staleTime: 30_000,
  });
}

export function guardrailVersionOptions(
  accessToken: string,
  name: string,
  versionNumber: number,
) {
  return queryOptions({
    queryKey: guardrailKeys.version(name, versionNumber),
    queryFn: ({ signal }) =>
      getGuardrailVersion(accessToken, name, versionNumber, signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
}
