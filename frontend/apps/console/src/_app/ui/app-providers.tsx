"use client";

import type { ReactNode } from "react";

import { SessionProvider } from "@/src/entities/session";

export function AppProviders({ children }: { children: ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
