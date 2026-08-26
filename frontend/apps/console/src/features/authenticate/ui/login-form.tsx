"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { useSession } from "@/src/entities/session";
import { ConsoleApiError, consoleErrorMessage } from "@/src/shared/api";

import { login } from "../api/login";
import styles from "./login-form.module.css";

type LoginReason = "expired" | "forbidden" | null;

const reasonMessages: Record<Exclude<LoginReason, null>, string> = {
  expired: "세션이 만료되었습니다. 계속하려면 다시 로그인하세요.",
  forbidden: "콘솔을 관리하려면 관리자 권한이 필요합니다.",
};

export function LoginForm({
  reason,
  returnTo,
}: {
  reason: LoginReason;
  returnTo: string | null;
}) {
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
      router.replace(returnTo ?? "/providers");
    } catch (caught) {
      if (caught instanceof ConsoleApiError && caught.code === "USER-001") {
        setError("이메일 또는 비밀번호가 올바르지 않습니다.");
      } else if (caught instanceof ConsoleApiError) {
        setError(consoleErrorMessage(caught));
      } else {
        setError("로그인하지 못했습니다. 입력 내용을 확인한 뒤 다시 시도하세요.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.heading}>
        <p className={styles.kicker}>콘솔 접근</p>
        <h2>관리자 로그인</h2>
        <p>관리자 계정으로 모델 경로와 가드레일을 관리하세요.</p>
      </div>

      {error ? (
        <div className={styles.error} role="alert">
          <span aria-hidden="true">!</span>
          <p>{error}</p>
        </div>
      ) : null}

      <label className={styles.field}>
        <span>이메일</span>
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
        <span>비밀번호</span>
        <input
          type="password"
          name="password"
          autoComplete="current-password"
          placeholder="비밀번호 입력"
          required
        />
      </label>

      <button className={styles.submit} type="submit" disabled={isSubmitting}>
        {isSubmitting ? (
          <>
            <span className={styles.spinner} aria-hidden="true" />
            콘솔을 여는 중…
          </>
        ) : (
          <>
            로그인
            <span aria-hidden="true">→</span>
          </>
        )}
      </button>
    </form>
  );
}
