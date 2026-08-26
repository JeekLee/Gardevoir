import type { Metadata } from "next";

import { LoginPage } from "@/src/_pages/login";

export const metadata: Metadata = {
  title: "로그인",
};

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string; returnTo?: string }>;
}) {
  const { reason, returnTo } = await searchParams;
  const loginReason =
    reason === "expired" || reason === "forbidden" ? reason : null;
  const safeReturnTo =
    returnTo?.startsWith("/guardrails/") && !returnTo.startsWith("//")
      ? returnTo
      : null;

  return <LoginPage reason={loginReason} returnTo={safeReturnTo} />;
}
