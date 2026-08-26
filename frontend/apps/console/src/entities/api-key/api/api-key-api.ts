import { apiRequest } from "@/src/shared/api";

import {
  parseApiKeyCreated,
  parseApiKeyPage,
  parseApiKeySummary,
  type CreateApiKeyInput,
  type UpdateApiKeyInput,
} from "../model/api-key";

export function listApiKeys(accessToken: string, signal?: AbortSignal) {
  return apiRequest({
    path: "/api-keys",
    accessToken,
    signal,
    parse: parseApiKeyPage,
  });
}

export function createApiKey(accessToken: string, input: CreateApiKeyInput) {
  return apiRequest({
    path: "/api-keys",
    method: "POST",
    accessToken,
    body: input,
    parse: parseApiKeyCreated,
  });
}

export function updateApiKey(
  accessToken: string,
  apiKeyId: string,
  input: UpdateApiKeyInput,
) {
  return apiRequest({
    path: `/api-keys/${encodeURIComponent(apiKeyId)}`,
    method: "PUT",
    accessToken,
    body: input,
    parse: parseApiKeySummary,
  });
}

export function revokeApiKey(accessToken: string, apiKeyId: string) {
  return apiRequest({
    path: `/api-keys/${encodeURIComponent(apiKeyId)}/revoke`,
    method: "POST",
    accessToken,
  });
}
