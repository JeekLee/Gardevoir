import type { Metadata } from "next";

import { ProvidersPage } from "@/src/_pages/providers";

export const metadata: Metadata = {
  title: "프로바이더",
};

export default function Page() {
  return <ProvidersPage />;
}
