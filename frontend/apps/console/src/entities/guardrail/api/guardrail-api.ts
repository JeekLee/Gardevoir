import { apiRequest } from "@/src/shared/api";

import {
  parseGuardrailDetail,
  parseGuardrailPage,
  type GuardrailGraph,
} from "../model/guardrail";

export function listGuardrails(accessToken: string, signal?: AbortSignal) {
  return apiRequest({
    path: "/guardrails",
    accessToken,
    signal,
    parse: parseGuardrailPage,
  });
}

export function createGuardrail(
  accessToken: string,
  input: { name: string; description?: string; graph: GuardrailGraph },
) {
  return apiRequest({
    path: "/guardrails",
    method: "POST",
    accessToken,
    body: input,
    parse: parseGuardrailDetail,
  });
}

export function getGuardrailDraft(
  accessToken: string,
  name: string,
  signal?: AbortSignal,
) {
  return apiRequest({
    path: `/guardrails/${encodeURIComponent(name)}/draft`,
    accessToken,
    signal,
    parse: parseGuardrailDetail,
  });
}

export function updateGuardrailDraft(
  accessToken: string,
  name: string,
  draft: { description: string; graph: GuardrailGraph },
) {
  return apiRequest({
    path: `/guardrails/${encodeURIComponent(name)}/draft`,
    method: "PUT",
    accessToken,
    body: draft,
    parse: parseGuardrailDetail,
  });
}

export function publishGuardrail(accessToken: string, name: string) {
  return apiRequest({
    path: `/guardrails/${encodeURIComponent(name)}/publish`,
    method: "POST",
    accessToken,
    parse: parseGuardrailDetail,
  });
}

export function getGuardrailVersion(
  accessToken: string,
  name: string,
  versionNumber: number,
  signal?: AbortSignal,
) {
  return apiRequest({
    path: `/guardrails/${encodeURIComponent(name)}/versions/${versionNumber}`,
    accessToken,
    signal,
    parse: parseGuardrailDetail,
  });
}
