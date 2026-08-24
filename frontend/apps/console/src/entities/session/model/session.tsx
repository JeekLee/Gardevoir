"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
} from "react";

export type Role = "admin" | "user";

export type UserSummary = {
  id: string;
  email: string;
  name: string;
  role: Role;
  deactivatedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type TokenPair = {
  accessToken: string;
  refreshToken: string;
  tokenType: "Bearer";
  expiresIn: number;
};

export type Session = {
  tokens: TokenPair;
  user: UserSummary;
};

type SessionContextValue = {
  session: Session | null;
  isReady: boolean;
  establishSession: (session: Session) => void;
  endSession: () => void;
};

const STORAGE_KEY = "gardevoir.console.session.v1";
const SessionContext = createContext<SessionContextValue | null>(null);
const serverSnapshot = { session: null, isReady: false } as const;
const listeners = new Set<() => void>();
let store: { session: Session | null; isReady: boolean } = serverSnapshot;
let initialized = false;

export function SessionProvider({ children }: { children: ReactNode }) {
  const { session, isReady } = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  const establishSession = useCallback((nextSession: Session) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession));
    updateStore(nextSession);
  }, []);

  const endSession = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    updateStore(null);
  }, []);

  const value = useMemo(
    () => ({ session, isReady, establishSession, endSession }),
    [session, isReady, establishSession, endSession],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used within SessionProvider");
  }
  return value;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!initialized) {
    initialized = true;
    store = { session: readStoredSession(), isReady: true };
    queueMicrotask(emitChange);
  }
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return store;
}

function getServerSnapshot() {
  return serverSnapshot;
}

function updateStore(session: Session | null) {
  initialized = true;
  store = { session, isReady: true };
  emitChange();
}

function emitChange() {
  listeners.forEach((listener) => listener());
}

function readStoredSession(): Session | null {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (!stored) {
    return null;
  }

  try {
    const value: unknown = JSON.parse(stored);
    if (isSession(value)) {
      return value;
    }
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }

  localStorage.removeItem(STORAGE_KEY);
  return null;
}

export function parseSession(value: unknown): Session {
  if (!isSession(value)) {
    throw new Error("Invalid login response");
  }
  return value;
}

function isSession(value: unknown): value is Session {
  if (!isRecord(value) || !isRecord(value.tokens) || !isRecord(value.user)) {
    return false;
  }

  const { tokens, user } = value;
  return (
    typeof tokens.accessToken === "string" &&
    typeof tokens.refreshToken === "string" &&
    tokens.tokenType === "Bearer" &&
    typeof tokens.expiresIn === "number" &&
    typeof user.id === "string" &&
    typeof user.email === "string" &&
    typeof user.name === "string" &&
    (user.role === "admin" || user.role === "user") &&
    (user.deactivatedAt === null || typeof user.deactivatedAt === "string") &&
    typeof user.createdAt === "string" &&
    typeof user.updatedAt === "string"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
