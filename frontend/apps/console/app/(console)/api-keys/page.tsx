import type { Metadata } from "next";

import { ApiKeysPage } from "@/src/_pages/api-keys";

export const metadata: Metadata = {
  title: "API 키",
};

export default function Page() {
  return <ApiKeysPage />;
}
