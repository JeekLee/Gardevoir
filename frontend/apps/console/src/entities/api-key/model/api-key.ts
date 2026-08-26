export type ApiKeySummary = {
  id: string;
  name: string;
  keyPreview: string;
  expiresAt: string | null;
  revokedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type ApiKeyCreated = {
  id: string;
  name: string;
  key: string;
  expiresAt: string | null;
};

export type ApiKeyPage = {
  items: ApiKeySummary[];
  total: number;
};

export type CreateApiKeyInput = {
  name: string;
  expiresAt?: string;
};

export type UpdateApiKeyInput = {
  name: string;
  expiresAt: string | null;
};

export type ApiKeyStatus = "active" | "revoked" | "expired";

export function apiKeyStatus(
  apiKey: Pick<ApiKeySummary, "expiresAt" | "revokedAt">,
  now = new Date(),
): ApiKeyStatus {
  if (apiKey.revokedAt !== null) return "revoked";
  if (apiKey.expiresAt !== null && new Date(apiKey.expiresAt) <= now) {
    return "expired";
  }
  return "active";
}

export function parseApiKeyPage(value: unknown): ApiKeyPage {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    typeof value.total !== "number"
  ) {
    throw new Error("Invalid API key list response");
  }

  return {
    items: value.items.map(parseApiKeySummary),
    total: value.total,
  };
}

export function parseApiKeyCreated(value: unknown): ApiKeyCreated {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.key !== "string" ||
    !isNullableTimestamp(value.expiresAt)
  ) {
    throw new Error("Invalid created API key response");
  }

  return {
    id: value.id,
    name: value.name,
    key: value.key,
    expiresAt: value.expiresAt,
  };
}

export function parseApiKeySummary(value: unknown): ApiKeySummary {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.keyPreview !== "string" ||
    !isNullableTimestamp(value.expiresAt) ||
    !isNullableTimestamp(value.revokedAt) ||
    typeof value.createdAt !== "string" ||
    typeof value.updatedAt !== "string"
  ) {
    throw new Error("Invalid API key response");
  }

  return {
    id: value.id,
    name: value.name,
    keyPreview: value.keyPreview,
    expiresAt: value.expiresAt,
    revokedAt: value.revokedAt,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  };
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
