"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/src/entities/session";
import { apiRequest } from "@/src/shared/api";

import styles from "./logout-button.module.css";

export function LogoutButton() {
  const router = useRouter();
  const { session, endSession } = useSession();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function logout() {
    if (isSubmitting) {
      return;
    }
    setIsSubmitting(true);

    try {
      if (session?.tokens.refreshToken) {
        await apiRequest({
          path: "/auth/logout",
          method: "POST",
          body: { refreshToken: session.tokens.refreshToken },
        });
      }
    } catch {
      // 로컬 세션은 게이트웨이 로그아웃 결과와 관계없이 반드시 폐기한다.
    } finally {
      endSession();
      router.replace("/login");
    }
  }

  return (
    <button
      className={styles.button}
      type="button"
      onClick={() => void logout()}
      disabled={isSubmitting}
    >
      {isSubmitting ? "로그아웃하는 중…" : "로그아웃"}
    </button>
  );
}
