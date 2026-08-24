import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";
import "@/src/_app/styles/globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/src/_app/ui";

export const metadata: Metadata = {
  title: {
    default: "Gardevoir console",
    template: "%s · Gardevoir",
  },
  description: "Control the model routes protected by Gardevoir.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
