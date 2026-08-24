"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "@/src/entities/session";
import { ConsoleApiError } from "@/src/shared/api";

import { login } from "../api/login";
import styles from "./login-form.module.css";

type LoginReason = "expired" | "forbidden" | null;

const reasonMessages: Record<Exclude<LoginReason, null>, string> = {
  expired: "Your session ended. Sign in to continue.",
  forbidden: "Administrator access is required for provider management.",
};

export function LoginForm({ reason }: { reason: LoginReason }) {
  const router = useRouter();
  const { session, isReady, establishSession, endSession } = useSession();
  const [error, setError] = useState<string | null>(
    reason ? reasonMessages[reason] : null,
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (isReady && session?.user.role === "admin" && !reason) {
      router.replace("/providers");
    }
  }, [isReady, reason, router, session]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");

    try {
      const nextSession = await login({ email, password });
      if (nextSession.user.role !== "admin") {
        endSession();
        setError(reasonMessages.forbidden);
        return;
      }
      establishSession(nextSession);
      router.replace("/providers");
    } catch (caught) {
      if (caught instanceof ConsoleApiError && caught.code === "USER-001") {
        setError("Email or password is incorrect.");
      } else if (caught instanceof ConsoleApiError) {
        setError(caught.message);
      } else {
        setError("Sign-in could not be completed. Try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.heading}>
        <p className={styles.kicker}>Console access</p>
        <h2>Welcome back</h2>
        <p>Use your administrator account to manage model routes.</p>
      </div>

      {error ? (
        <div className={styles.error} role="alert">
          <span aria-hidden="true">!</span>
          <p>{error}</p>
        </div>
      ) : null}

      <label className={styles.field}>
        <span>Email</span>
        <input
          type="email"
          name="email"
          autoComplete="email"
          placeholder="admin@example.com"
          required
          autoFocus
        />
      </label>

      <label className={styles.field}>
        <span>Password</span>
        <input
          type="password"
          name="password"
          autoComplete="current-password"
          placeholder="Enter your password"
          required
        />
      </label>

      <button className={styles.submit} type="submit" disabled={isSubmitting}>
        {isSubmitting ? (
          <>
            <span className={styles.spinner} aria-hidden="true" />
            Opening console
          </>
        ) : (
          <>
            Sign in
            <span aria-hidden="true">→</span>
          </>
        )}
      </button>
    </form>
  );
}
