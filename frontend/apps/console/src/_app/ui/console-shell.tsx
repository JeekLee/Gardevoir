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
      const returnTo =
        pathname.startsWith("/guardrails/") && !pathname.includes("/versions/")
          ? `&returnTo=${encodeURIComponent(pathname)}`
          : "";
      router.replace(`/login?reason=expired${returnTo}`);
      return;
    }
    if (session.user.role !== "admin") {
      endSession();
      router.replace("/login?reason=forbidden");
    }
  }, [endSession, isReady, pathname, router, session]);

  if (!isReady || !session || session.user.role !== "admin") {
    return (
      <main className={styles.loading} aria-live="polite">
        <GardevoirMark />
        <p>콘솔 접근 권한을 확인하는 중…</p>
      </main>
    );
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link className={styles.brand} href="/guardrails" aria-label="Gardevoir 콘솔 홈">
          <GardevoirMark compact />
          <span>
            <strong>gardevoir</strong>
            <small>통제실</small>
          </span>
        </Link>

        <nav className={styles.navigation} aria-label="콘솔 메뉴">
          <Link
            aria-current={pathname.startsWith("/guardrails") ? "page" : undefined}
            href="/guardrails"
          >
            가드레일
          </Link>
          <Link
            aria-current={pathname.startsWith("/providers") ? "page" : undefined}
            href="/providers"
          >
            프로바이더
          </Link>
          <Link
            aria-current={pathname.startsWith("/api-keys") ? "page" : undefined}
            href="/api-keys"
          >
            API 키
          </Link>
          <Link
            aria-current={pathname.startsWith("/audit") ? "page" : undefined}
            href="/audit"
          >
            감사
          </Link>
        </nav>

        <div className={styles.account}>
          <span className={styles.identity}>
            <span className={styles.avatar} aria-hidden="true">
              {initials(session.user.name, session.user.email)}
            </span>
            <span className={styles.identityText}>
              <strong>{session.user.name}</strong>
              <small>관리자</small>
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
