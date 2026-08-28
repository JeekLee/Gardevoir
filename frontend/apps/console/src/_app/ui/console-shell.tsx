"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { useSession } from "@/src/entities/session";
import { LogoutButton } from "@/src/features/logout";
import { GardevoirMark } from "@/src/shared/ui/gardevoir-mark";
import {
  NavigationIcon,
  type NavigationIconName,
} from "@/src/shared/ui/navigation-icon";

import styles from "./console-shell.module.css";

const SIDEBAR_STORAGE_KEY = "gardevoir.console.sidebar.collapsed";
const NARROW_SCREEN_QUERY = "(max-width: 760px)";

const navigationItems = [
  { href: "/guardrails", label: "가드레일", icon: "guardrail" },
  { href: "/providers", label: "프로바이더", icon: "provider" },
  { href: "/api-keys", label: "API 키", icon: "key" },
  { href: "/audit", label: "감사", icon: "audit" },
] as const satisfies readonly {
  href: string;
  label: string;
  icon: NavigationIconName;
}[];

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { session, isReady, endSession } = useSession();
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() =>
    readSidebarCollapsed(isNarrowScreenNow()),
  );
  const [isNarrowScreen, setIsNarrowScreen] = useState(isNarrowScreenNow);

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

  useEffect(() => {
    const mediaQuery = window.matchMedia(NARROW_SCREEN_QUERY);
    const syncNarrowScreen = (event: MediaQueryListEvent) => {
      setIsNarrowScreen(event.matches);
    };

    mediaQuery.addEventListener("change", syncNarrowScreen);

    return () => mediaQuery.removeEventListener("change", syncNarrowScreen);
  }, []);

  useEffect(() => {
    storeSidebarCollapsed(isSidebarCollapsed);
  }, [isSidebarCollapsed]);

  useEffect(() => {
    if (!isNarrowScreen || isSidebarCollapsed) {
      return;
    }

    const collapseOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsSidebarCollapsed(true);
      }
    };

    window.addEventListener("keydown", collapseOnEscape);
    return () => window.removeEventListener("keydown", collapseOnEscape);
  }, [isNarrowScreen, isSidebarCollapsed]);

  if (!isReady || !session || session.user.role !== "admin") {
    return (
      <main className={styles.loading} aria-live="polite">
        <GardevoirMark />
        <p>콘솔 접근 권한을 확인하는 중…</p>
      </main>
    );
  }

  return (
    <div
      className={styles.shell}
      data-sidebar-collapsed={isSidebarCollapsed}
    >
      <aside className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <Link
            className={styles.brand}
            href="/guardrails"
            aria-label="Gardevoir 콘솔 홈"
          >
            <GardevoirMark compact />
            <span className={styles.brandLabel}>
              <strong>gardevoir</strong>
            </span>
          </Link>
          <button
            className={styles.sidebarToggle}
            type="button"
            aria-controls="console-sidebar-navigation"
            aria-expanded={!isSidebarCollapsed}
            aria-label={isSidebarCollapsed ? "사이드바 펼치기" : "사이드바 접기"}
            onClick={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
          >
            <span aria-hidden="true">{isSidebarCollapsed ? "›" : "‹"}</span>
          </button>
        </div>

        <nav
          className={styles.navigation}
          id="console-sidebar-navigation"
          aria-label="콘솔 메뉴"
        >
          {navigationItems.map((item) => (
            <Link
              key={item.href}
              aria-current={pathname.startsWith(item.href) ? "page" : undefined}
              aria-label={item.label}
              href={item.href}
              title={item.label}
              onClick={() => {
                if (isNarrowScreen) {
                  setIsSidebarCollapsed(true);
                }
              }}
            >
              <NavigationIcon name={item.icon} />
              <span className={styles.navigationLabel}>{item.label}</span>
            </Link>
          ))}
        </nav>

        <div className={styles.account}>
          <span
            className={styles.identity}
            title={`${session.user.name || session.user.email} · 관리자`}
          >
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
      </aside>
      {isNarrowScreen && !isSidebarCollapsed ? (
        <button
          className={styles.backdrop}
          type="button"
          tabIndex={-1}
          aria-label="사이드바 닫기"
          onClick={() => setIsSidebarCollapsed(true)}
        />
      ) : null}
      <main className={styles.main}>{children}</main>
    </div>
  );
}

function readSidebarCollapsed(defaultValue: boolean): boolean {
  if (typeof window === "undefined") {
    return defaultValue;
  }
  try {
    const storedValue = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (storedValue === "true") {
      return true;
    }
    if (storedValue === "false") {
      return false;
    }
  } catch {
    return defaultValue;
  }
  return defaultValue;
}

function storeSidebarCollapsed(isCollapsed: boolean): void {
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(isCollapsed));
  } catch {
    return;
  }
}

function isNarrowScreenNow(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia(NARROW_SCREEN_QUERY).matches
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
