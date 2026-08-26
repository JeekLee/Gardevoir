import type { Metadata } from "next";
import { Suspense } from "react";

import { AuditPage } from "@/src/_pages/audit";

export const metadata: Metadata = {
  title: "감사",
};

export default function Page() {
  return (
    <Suspense fallback={<p aria-live="polite">감사 기록을 준비하는 중…</p>}>
      <AuditPage />
    </Suspense>
  );
}
