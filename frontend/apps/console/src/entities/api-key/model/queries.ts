import { queryOptions } from "@tanstack/react-query";

import { listApiKeys } from "../api/api-key-api";

export const apiKeyKeys = {
  all: ["api-keys"] as const,
  list: () => ["api-keys", "list"] as const,
};

export function apiKeyListOptions(accessToken: string) {
  return queryOptions({
    queryKey: apiKeyKeys.list(),
    queryFn: ({ signal }) => listApiKeys(accessToken, signal),
    staleTime: 15_000,
  });
}
