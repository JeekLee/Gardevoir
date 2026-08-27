import { LoginForm } from "@/src/features/authenticate";
import { GardevoirMark } from "@/src/shared/ui/gardevoir-mark";

import styles from "./login-page.module.css";

export function LoginPage({
  reason,
  returnTo,
}: {
  reason: "expired" | "forbidden" | null;
  returnTo: string | null;
}) {
  return (
    <main className={styles.page}>
      <section className={styles.access} aria-label="로그인">
        <div className={styles.login}>
          <div className={styles.brand}>
            <GardevoirMark />
            <span>
              <strong>gardevoir</strong>
              <small>통제실</small>
            </span>
          </div>
          <LoginForm reason={reason} returnTo={returnTo} />
          <p className={styles.footnote}>
            콘솔 계정은 애플리케이션 <code>gdv_</code> 키와 별도로 관리됩니다.
          </p>
        </div>
      </section>
    </main>
  );
}
