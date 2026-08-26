import type { Metadata } from "next";

import { GuardrailsPage } from "@/src/_pages/guardrails";

export const metadata: Metadata = {
  title: "가드레일",
};

export default function Page() {
  return <GuardrailsPage />;
}
