import type { ReactNode } from "react";

import { ConsoleShell } from "@/src/_app/ui";

export default function Layout({ children }: { children: ReactNode }) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
