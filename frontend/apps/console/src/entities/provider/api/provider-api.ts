import { apiRequest } from "@/src/shared/api";

import {
  parseProvider,
  parseProviderPage,
  type CreateProviderInput,
  type UpdateProviderInput,
} from "../model/provider";

export function listProviders(accessToken: string, signal?: AbortSignal) {
  return apiRequest({
    path: "/providers",
    accessToken,
    signal,
    parse: parseProviderPage,
  });
}

export function createProvider(accessToken: string, input: CreateProviderInput) {
  return apiRequest({
    path: "/providers",
    method: "POST",
    accessToken,
    body: input,
    parse: parseProvider,
  });
}

export function updateProvider(
  accessToken: string,
  providerId: string,
  input: UpdateProviderInput,
) {
  return apiRequest({
    path: `/providers/${encodeURIComponent(providerId)}`,
    method: "PUT",
    accessToken,
    body: input,
    parse: parseProvider,
  });
}

export function deleteProvider(accessToken: string, providerId: string) {
  return apiRequest({
    path: `/providers/${encodeURIComponent(providerId)}`,
    method: "DELETE",
    accessToken,
  });
}
