import type { Metadata } from "next";

import { GuardrailEditorPage } from "@/src/_pages/guardrail-editor";

export const metadata: Metadata = {
  title: "가드레일 초안",
};

export default async function Page({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = await params;
  return <GuardrailEditorPage name={name} />;
}
