import type { Metadata } from "next";

import { GuardrailsPage } from "@/src/_pages/guardrails";

export const metadata: Metadata = {
  title: "Guardrails",
};

export default function Page() {
  return <GuardrailsPage />;
}
