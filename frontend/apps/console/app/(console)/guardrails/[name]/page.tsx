import type { Metadata } from "next";

import { GuardrailEditorPage } from "@/src/_pages/guardrail-editor";

export const metadata: Metadata = {
  title: "Guardrail draft",
};

export default async function Page({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = await params;
  return <GuardrailEditorPage name={name} />;
}
