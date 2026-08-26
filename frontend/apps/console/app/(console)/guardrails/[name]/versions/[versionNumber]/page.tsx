import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { GuardrailEditorPage } from "@/src/_pages/guardrail-editor";

export const metadata: Metadata = {
  title: "가드레일 발행본",
};

export default async function Page({
  params,
}: {
  params: Promise<{ name: string; versionNumber: string }>;
}) {
  const { name, versionNumber: rawVersionNumber } = await params;
  const versionNumber = Number(rawVersionNumber);
  if (!Number.isInteger(versionNumber) || versionNumber < 1) notFound();

  return <GuardrailEditorPage name={name} versionNumber={versionNumber} />;
}
