export type GardevoirMode = "enforce" | "dry-run";

export function buildAppConnectionSnippet({
  endpoint,
  apiKey,
  guardrailName,
  mode,
}: {
  endpoint: string;
  apiKey: string;
  guardrailName: string;
  mode: GardevoirMode;
}): string {
  const headers = [
    "Content-Type: application/json",
    `Authorization: Bearer ${apiKey}`,
    `X-Gardevoir-Guardrail: ${guardrailName}`,
  ];
  if (mode === "dry-run") {
    headers.push("X-Gardevoir-Mode: dry-run");
  }

  const body = JSON.stringify(
    {
      model: "gpt-5.2",
      messages: [{ role: "user", content: "안녕하세요" }],
    },
    null,
    2,
  );

  return [
    `curl --request POST ${shellQuote(endpoint)} \\`,
    ...headers.map((header) => `  --header ${shellQuote(header)} \\`),
    `  --data ${shellQuote(body)}`,
  ].join("\n");
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}
