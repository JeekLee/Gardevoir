export type ProviderSummary = {
  id: string;
  name: string;
  baseUrl: string;
  models: string[];
  hasApiKey: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ProviderPage = {
  items: ProviderSummary[];
  total: number;
};

type ProviderBaseInput = {
  name: string;
  baseUrl: string;
  models: string[];
};

export type CreateProviderInput = ProviderBaseInput & {
  apiKey: string;
};

export type UpdateProviderInput = ProviderBaseInput & {
  apiKey: string | null;
};

export function parseProvider(value: unknown): ProviderSummary {
  if (!isRecord(value)) {
    throw new Error("Invalid provider response");
  }

  const models = value.models;
  if (
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.baseUrl !== "string" ||
    !Array.isArray(models) ||
    !models.every((model) => typeof model === "string") ||
    typeof value.hasApiKey !== "boolean" ||
    typeof value.createdAt !== "string" ||
    typeof value.updatedAt !== "string"
  ) {
    throw new Error("Invalid provider response");
  }

  return {
    id: value.id,
    name: value.name,
    baseUrl: value.baseUrl,
    models,
    hasApiKey: value.hasApiKey,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  };
}

export function parseProviderPage(value: unknown): ProviderPage {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    typeof value.total !== "number"
  ) {
    throw new Error("Invalid provider list response");
  }

  return {
    items: value.items.map(parseProvider),
    total: value.total,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
