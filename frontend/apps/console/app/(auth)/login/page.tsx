import type { Metadata } from "next";

import { LoginPage } from "@/src/_pages/login";

export const metadata: Metadata = {
  title: "Sign in",
};

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string }>;
}) {
  const { reason } = await searchParams;
  const loginReason =
    reason === "expired" || reason === "forbidden" ? reason : null;

  return <LoginPage reason={loginReason} />;
}
