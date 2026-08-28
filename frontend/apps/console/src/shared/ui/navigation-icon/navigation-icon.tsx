export type NavigationIconName = "audit" | "guardrail" | "key" | "provider";

export function NavigationIcon({ name }: { name: NavigationIconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {name === "guardrail" ? <GuardrailIcon /> : null}
      {name === "provider" ? <ProviderIcon /> : null}
      {name === "key" ? <KeyIcon /> : null}
      {name === "audit" ? <AuditIcon /> : null}
    </svg>
  );
}

function GuardrailIcon() {
  return (
    <>
      <path d="M12 3 19 6v5c0 4.7-2.7 8-7 10-4.3-2-7-5.3-7-10V6l7-3Z" />
      <circle cx="9" cy="11" r="1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="9" r="1" fill="currentColor" stroke="none" />
      <circle cx="14" cy="15" r="1" fill="currentColor" stroke="none" />
      <path d="m10 10.7 4-1.4m-4.2 2.5 3.4 2.4" />
    </>
  );
}

function ProviderIcon() {
  return (
    <>
      <rect x="3" y="4" width="7" height="6" rx="1.5" />
      <rect x="14" y="14" width="7" height="6" rx="1.5" />
      <path d="M10 7h1.5a5 5 0 0 1 5 5v2M6 7h1m10.5 10h1" />
    </>
  );
}

function KeyIcon() {
  return (
    <>
      <circle cx="8" cy="9" r="4" />
      <path d="m10.8 11.8 8.2 8.2m-3-3 2-2m-5-1 2-2" />
    </>
  );
}

function AuditIcon() {
  return (
    <>
      <path d="M6 3h8l4 4v14H6V3Z" />
      <path d="M14 3v5h4M9 12h6m-6 4h6" />
    </>
  );
}
