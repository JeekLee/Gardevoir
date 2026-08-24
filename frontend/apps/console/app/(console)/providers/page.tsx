import type { Metadata } from "next";

import { ProvidersPage } from "@/src/_pages/providers";

export const metadata: Metadata = {
  title: "Providers",
};

export default function Page() {
  return <ProvidersPage />;
}
