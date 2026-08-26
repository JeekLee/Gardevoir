import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";
import "@/src/_app/styles/globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/src/_app/ui";

export const metadata: Metadata = {
  title: {
    default: "Gardevoir 콘솔",
    template: "%s · Gardevoir",
  },
  description: "Gardevoir가 보호하는 모델 경로를 관리합니다.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
