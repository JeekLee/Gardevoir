"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { useSession } from "@/src/entities/session";
import { LogoutButton } from "@/src/features/logout";
import { GardevoirMark } from "@/src/shared/ui/gardevoir-mark";

import styles from "./console-shell.module.css";

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { session, isReady, endSession } = useSession();

  useEffect(() => {
    if (!isReady) {
      return;
    }
    if (!session) {
      router.replace("/login?reason=expired");
      return;
    }
    if (session.user.role !== "admin") {
      endSession();
      router.replace("/login?reason=forbidden");
    }
  }, [endSession, isReady, router, session]);

  if (!isReady || !session || session.user.role !== "admin") {
    return (
      <main className={styles.loading} aria-live="polite">
        <GardevoirMark />
        <p>Verifying console access…</p>
      </main>
    );
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link className={styles.brand} href="/guardrails" aria-label="Gardevoir console home">
          <GardevoirMark compact />
          <span>
            <strong>gardevoir</strong>
            <small>control room</small>
          </span>
        </Link>

        <nav className={styles.navigation} aria-label="Console navigation">
          <Link
            aria-current={pathname.startsWith("/guardrails") ? "page" : undefined}
            href="/guardrails"
          >
            Guardrails
          </Link>
          <Link
            aria-current={pathname.startsWith("/providers") ? "page" : undefined}
            href="/providers"
          >
            Providers
          </Link>
        </nav>

        <div className={styles.account}>
          <span className={styles.identity}>
            <span className={styles.avatar} aria-hidden="true">
              {initials(session.user.name, session.user.email)}
            </span>
            <span className={styles.identityText}>
              <strong>{session.user.name}</strong>
              <small>Administrator</small>
            </span>
          </span>
          <LogoutButton />
        </div>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}

function initials(name: string, email: string): string {
  const source = name.trim() || email.split("@")[0] || "A";
  return source
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}
